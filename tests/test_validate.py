import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.validate import validate_pipeline_data

def test_orphan_order_detection():
    sig_df = pd.DataFrame([{
        "signal_id": "SIG_100", "timestamp": "2026-09-25T10:00:00+05:30",
        "symbol": "RELIANCE.NS", "side": "BUY", "signal_price": 2500.0, "quantity": 100
    }])
    ord_df = pd.DataFrame([{
        "order_id": "ORD_100", "signal_id": "SIG_999_ORPHAN",
        "order_placed_ts": "2026-09-25T10:00:01+05:30",
        "order_confirmed_ts": "2026-09-25T10:00:02+05:30",
        "fill_ts": "2026-09-25T10:00:03+05:30", "fill_price": 2501.0,
        "fill_qty": 100, "status": "FILLED", "reject_reason": "NONE"
    }])
    
    clean_sig, clean_ord, val_report = validate_pipeline_data(sig_df, ord_df)
    assert len(val_report) == 1
    assert val_report.iloc[0]["rule_failed"] == "ORPHAN_ORDER"
    assert len(clean_ord) == 0

def test_non_monotonic_timestamps():
    sig_df = pd.DataFrame([{
        "signal_id": "SIG_101", "timestamp": "2026-09-25T10:00:00+05:30",
        "symbol": "TCS.NS", "side": "BUY", "signal_price": 3500.0, "quantity": 50
    }])
    ord_df = pd.DataFrame([{
        "order_id": "ORD_101", "signal_id": "SIG_101",
        "order_placed_ts": "2026-09-25T10:00:05+05:30",
        "order_confirmed_ts": "2026-09-25T10:00:02+05:30",  # earlier than placed!
        "fill_ts": "2026-09-25T10:00:06+05:30", "fill_price": 3502.0,
        "fill_qty": 50, "status": "FILLED", "reject_reason": "NONE"
    }])
    
    clean_sig, clean_ord, val_report = validate_pipeline_data(sig_df, ord_df)
    assert len(val_report) > 0
    assert "NON_MONOTONIC_TIMESTAMPS" in val_report["rule_failed"].values

def test_off_market_hours_fill():
    sig_df = pd.DataFrame([{
        "signal_id": "SIG_102", "timestamp": "2026-09-25T02:00:00+05:30",
        "symbol": "INFY.NS", "side": "BUY", "signal_price": 1500.0, "quantity": 50
    }])
    ord_df = pd.DataFrame([{
        "order_id": "ORD_102", "signal_id": "SIG_102",
        "order_placed_ts": "2026-09-25T02:00:01+05:30",
        "order_confirmed_ts": "2026-09-25T02:00:02+05:30",
        "fill_ts": "2026-09-25T02:15:00+05:30",  # 2:15 AM
        "fill_price": 1501.0, "fill_qty": 50, "status": "FILLED", "reject_reason": "NONE"
    }])
    
    clean_sig, clean_ord, val_report = validate_pipeline_data(sig_df, ord_df)
    assert "OFF_MARKET_HOURS_FILL" in val_report["rule_failed"].values
