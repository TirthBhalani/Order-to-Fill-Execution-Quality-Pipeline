import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.metrics import compute_execution_metrics

def test_slippage_and_latency_math():
    model_rows = [
        {
            "order_id": "ORD_1", "signal_id": "SIG_1", "symbol": "RELIANCE.NS",
            "side": "BUY", "signal_ts": "2026-09-25T10:00:00+05:30", "signal_price": 2000.0,
            "order_qty": 100, "order_placed_ts": "2026-09-25T10:00:01+05:30",
            "order_confirmed_ts": "2026-09-25T10:00:02+05:30",
            "fill_ts": "2026-09-25T10:00:04+05:30",  # 4 seconds latency
            "fill_price": 2002.0, "fill_qty": 100, "status": "FILLED", "reject_reason": "NONE"
        },
        {
            "order_id": "ORD_2", "signal_id": "SIG_2", "symbol": "RELIANCE.NS",
            "side": "SELL", "signal_ts": "2026-09-25T10:00:00+05:30", "signal_price": 2000.0,
            "order_qty": 100, "order_placed_ts": "2026-09-25T10:00:01+05:30",
            "order_confirmed_ts": "2026-09-25T10:00:02+05:30",
            "fill_ts": "2026-09-25T10:00:06+05:30",  # 6 seconds latency
            "fill_price": 1998.0, "fill_qty": 100, "status": "FILLED", "reject_reason": "NONE"
        }
    ]
    
    df = pd.DataFrame(model_rows)
    ev_df = compute_execution_metrics(df)
    
    overall_row = ev_df[ev_df["symbol"] == "OVERALL"].iloc[0]
    
    # Latency: (4 + 6) / 2 = 5.0 seconds median
    assert overall_row["median_latency_sec"] == 5.0
    
    # Slippage math:
    # BUY: (2002 - 2000) / 2000 * 10000 = +10 bps
    # SELL: (2000 - 1998) / 2000 * 10000 = +10 bps
    # Avg slippage bps = 10.0
    assert overall_row["avg_slippage_bps"] == 10.0
    
    # Slippage cost in INR:
    # ORD_1: (10 / 10000) * 2002 * 100 = 200.20
    # ORD_2: (10 / 10000) * 1998 * 100 = 199.80
    # Total = 400.00 INR
    assert overall_row["total_slippage_cost_inr"] == 400.00
