import os
import sys
import pandas as pd
import numpy as np

# Ensure root workspace directory is in sys.path for IDE linting & script execution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PRICE_DEV_THRESHOLD = 0.05  # 5% max deviation between signal and fill price

def validate_pipeline_data(sig_df, ord_df):
    report_rows = []
    
    # Merge signals and orders temporarily for validation
    df = pd.merge(ord_df, sig_df, on="signal_id", how="left", suffixes=("_ord", "_sig"))
    
    for idx, row in df.iterrows():
        ord_id = row["order_id"]
        sig_id = row["signal_id"]
        
        # Rule 1: Orphan Order (missing signal reference)
        if pd.isna(row.get("symbol")):
            report_rows.append({
                "order_id": ord_id,
                "signal_id": sig_id,
                "rule_failed": "ORPHAN_ORDER",
                "details": f"Order {ord_id} references missing signal {sig_id}"
            })
            continue

        status = row.get("status")
        
        # If order was rejected, fill_ts/fill_price check might be empty which is expected
        placed_ts = pd.to_datetime(row.get("order_placed_ts"), errors="coerce")
        confirmed_ts = pd.to_datetime(row.get("order_confirmed_ts"), errors="coerce")
        fill_ts = pd.to_datetime(row.get("fill_ts"), errors="coerce")
        
        # Rule 2: Timestamp monotonicity check
        if pd.notna(placed_ts) and pd.notna(confirmed_ts) and confirmed_ts < placed_ts:
            report_rows.append({
                "order_id": ord_id,
                "signal_id": sig_id,
                "rule_failed": "NON_MONOTONIC_TIMESTAMPS",
                "details": f"order_confirmed_ts ({confirmed_ts}) < order_placed_ts ({placed_ts})"
            })
            
        if pd.notna(confirmed_ts) and pd.notna(fill_ts) and fill_ts < confirmed_ts:
            report_rows.append({
                "order_id": ord_id,
                "signal_id": sig_id,
                "rule_failed": "NON_MONOTONIC_TIMESTAMPS",
                "details": f"fill_ts ({fill_ts}) < order_confirmed_ts ({confirmed_ts})"
            })

        # Rules for filled or partial orders
        if status in ["FILLED", "PARTIAL"]:
            # Rule 3: Fill quantity exceeded
            qty = float(row.get("quantity", 0))
            fill_qty = float(row.get("fill_qty", 0))
            if fill_qty > qty:
                report_rows.append({
                    "order_id": ord_id,
                    "signal_id": sig_id,
                    "rule_failed": "QUANTITY_EXCEEDED",
                    "details": f"fill_qty ({fill_qty}) exceeds signal quantity ({qty})"
                })

            # Rule 4: Price band violation (> 5% deviation)
            sig_p = float(row.get("signal_price", 0))
            fill_p = float(row.get("fill_price", 0)) if pd.notna(row.get("fill_price")) else 0
            if sig_p > 0 and fill_p > 0:
                dev = abs(fill_p - sig_p) / sig_p
                if dev > PRICE_DEV_THRESHOLD:
                    report_rows.append({
                        "order_id": ord_id,
                        "signal_id": sig_id,
                        "rule_failed": "PRICE_BAND_VIOLATION",
                        "details": f"Fill price {fill_p} is {dev*100:.2f}% away from signal price {sig_p}"
                    })

            # Rule 5: Non-market hours fill (NSE market hours 9:15 to 15:30 IST)
            if pd.notna(fill_ts):
                t = fill_ts.time()
                mkt_start = pd.to_datetime("09:15:00").time()
                mkt_end = pd.to_datetime("15:30:00").time()
                if not (mkt_start <= t <= mkt_end):
                    report_rows.append({
                        "order_id": ord_id,
                        "signal_id": sig_id,
                        "rule_failed": "OFF_MARKET_HOURS_FILL",
                        "details": f"fill_ts ({t}) occurred outside NSE market hours 09:15-15:30"
                    })

    val_report_df = pd.DataFrame(report_rows)
    
    # Filter out invalid order_ids from clean orders
    invalid_ord_ids = set(val_report_df["order_id"].unique()) if not val_report_df.empty else set()
    clean_ord_df = ord_df[~ord_df["order_id"].isin(invalid_ord_ids)].copy()
    clean_sig_df = sig_df.copy()
    
    return clean_sig_df, clean_ord_df, val_report_df

if __name__ == "__main__":
    sig_df = pd.read_csv("data/raw/signals.csv")
    ord_df = pd.read_csv("data/raw/orders.csv")
    c_sig, c_ord, rpt = validate_pipeline_data(sig_df, ord_df)
    print(f"Validation finished. Found {len(rpt)} rule violations.")
    if not rpt.empty:
        print(rpt)
