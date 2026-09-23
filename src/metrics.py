import os
import sys
import pandas as pd
import numpy as np

# Ensure root workspace directory is in sys.path for IDE linting & script execution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def compute_execution_metrics(model_df):
    if model_df.empty:
        return pd.DataFrame()

    df = model_df.copy()
    
    # Datetime conversions
    df["sig_dt"] = pd.to_datetime(df["signal_ts"], errors="coerce")
    df["fill_dt"] = pd.to_datetime(df["fill_ts"], errors="coerce")
    
    # 1. Signal-to-fill latency (seconds)
    df["latency_sec"] = (df["fill_dt"] - df["sig_dt"]).dt.total_seconds()
    
    # 2. Slippage in basis points (adverse slippage is positive)
    # BUY: fill > sig is adverse (+). SELL: fill < sig is adverse (+).
    df["slippage_bps"] = np.where(
        df["side"] == "BUY",
        (df["fill_price"] - df["signal_price"]) / df["signal_price"] * 10000.0,
        (df["signal_price"] - df["fill_price"]) / df["signal_price"] * 10000.0
    )
    
    # Filter out unfilled/rejected rows for price/latency metrics
    exec_mask = df["status"].isin(["FILLED", "PARTIAL"]) & pd.notna(df["fill_price"])
    
    # 5. Estimated slippage cost in INR
    # slippage_bps / 10000 * fill_price * fill_qty
    df["slippage_cost_inr"] = np.where(
        exec_mask,
        (df["slippage_bps"] / 10000.0) * df["fill_price"] * df["fill_qty"],
        0.0
    )
    
    symbols = list(df["symbol"].unique()) + ["OVERALL"]
    evidence_rows = []
    
    for sym in symbols:
        if sym == "OVERALL":
            sub = df
        else:
            sub = df[df["symbol"] == sym]
            
        tot_orders = len(sub)
        if tot_orders == 0:
            continue
            
        filled_orders = len(sub[sub["status"] == "FILLED"])
        partial_orders = len(sub[sub["status"] == "PARTIAL"])
        rejected_orders = len(sub[sub["status"] == "REJECTED"])
        
        fill_rate_pct = round((filled_orders / tot_orders) * 100, 2)
        partial_rate_pct = round((partial_orders / tot_orders) * 100, 2)
        reject_rate_pct = round((rejected_orders / tot_orders) * 100, 2)
        
        # Latency & slippage stats on executed orders
        sub_exec = sub[sub["status"].isin(["FILLED", "PARTIAL"]) & pd.notna(sub["latency_sec"])]
        
        if not sub_exec.empty:
            med_latency = round(float(sub_exec["latency_sec"].median()), 3)
            p95_latency = round(float(sub_exec["latency_sec"].quantile(0.95)), 3)
            avg_slippage_bps = round(float(sub_exec["slippage_bps"].mean()), 2)
        else:
            med_latency = 0.0
            p95_latency = 0.0
            avg_slippage_bps = 0.0
            
        total_slippage_cost_inr = round(float(sub["slippage_cost_inr"].sum()), 2)
        
        # Rejection reasons breakdown
        rej_sub = sub[sub["status"] == "REJECTED"]
        top_rej_reason = rej_sub["reject_reason"].mode()[0] if not rej_sub.empty else "NONE"
        
        evidence_rows.append({
            "symbol": sym,
            "total_orders": tot_orders,
            "filled_orders": filled_orders,
            "partial_orders": partial_orders,
            "rejected_orders": rejected_orders,
            "fill_rate_pct": fill_rate_pct,
            "partial_rate_pct": partial_rate_pct,
            "rejection_rate_pct": reject_rate_pct,
            "median_latency_sec": med_latency,
            "p95_latency_sec": p95_latency,
            "avg_slippage_bps": avg_slippage_bps,
            "total_slippage_cost_inr": total_slippage_cost_inr,
            "top_rejection_reason": top_rej_reason
        })
        
    return pd.DataFrame(evidence_rows)

if __name__ == "__main__":
    from src.validate import validate_pipeline_data
    from src.model import build_workflow_model
    sig_df = pd.read_csv("data/raw/signals.csv")
    ord_df = pd.read_csv("data/raw/orders.csv")
    c_sig, c_ord, _ = validate_pipeline_data(sig_df, ord_df)
    m_df = build_workflow_model(c_sig, c_ord)
    ev_table = compute_execution_metrics(m_df)
    print("Evidence Table generated:")
    print(ev_table.to_string())
