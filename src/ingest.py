import os
import random
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

# Note: Market price data is fetched live from yfinance (real exchange data).
# Order and Signal data are synthetically generated because live broker API feeds
# are proprietary/restricted.

SYMBOLS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]

def fetch_market_prices(symbols=SYMBOLS, period="5d", interval="5m"):
    dfs = []
    for sym in symbols:
        ticker = yf.Ticker(sym)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            continue
        df = df.reset_index()
        df["symbol"] = sym
        # standardizing col names
        cols = {c: c.lower() for c in df.columns}
        df = df.rename(columns=cols)
        if "datetime" in df.columns:
            df = df.rename(columns={"datetime": "timestamp"})
        elif "date" in df.columns:
            df = df.rename(columns={"date": "timestamp"})
        
        dfs.append(df[["timestamp", "symbol", "open", "high", "low", "close", "volume"]])
    
    if not dfs:
        # fallback dummy market data if network/yfinance issue occurs
        now = datetime.now()
        dummy_rows = []
        for sym in symbols:
            for i in range(50):
                ts = now - timedelta(minutes=5*i)
                dummy_rows.append({
                    "timestamp": ts, "symbol": sym, 
                    "open": 2500.0, "high": 2510.0, "low": 2490.0, "close": 2505.0, "volume": 1000
                })
        return pd.DataFrame(dummy_rows)
        
    return pd.concat(dfs, ignore_index=True)

def generate_synthetic_logs(market_df, num_signals=300):
    random.seed(42)
    timestamps = market_df["timestamp"].dropna().tolist()
    
    signals = []
    orders = []
    
    for i in range(1, num_signals + 1):
        sig_id = f"SIG_{1000 + i}"
        ref_row = market_df.sample(1).iloc[0]
        ts = ref_row["timestamp"]
        if not isinstance(ts, pd.Timestamp):
            ts = pd.Timestamp(ts)
            
        sym = ref_row["symbol"]
        side = random.choice(["BUY", "SELL"])
        base_price = float(ref_row["close"])
        sig_price = round(base_price * random.uniform(0.998, 1.002), 2)
        qty = random.choice([50, 100, 200, 500, 1000])
        
        signals.append({
            "signal_id": sig_id,
            "timestamp": ts.isoformat(),
            "symbol": sym,
            "side": side,
            "signal_price": sig_price,
            "quantity": qty
        })
        
        # Order creation
        ord_id = f"ORD_{5000 + i}"
        
        # Inject intentional edge case noise for validation testing
        # 1. Orphan order (no signal_id match)
        assoc_sig_id = sig_id
        if i == 15:
            assoc_sig_id = "SIG_9999_ORPHAN"
            
        # 2. Non-monotonic timestamps
        placed_dt = ts + timedelta(seconds=random.uniform(0.1, 1.5))
        if i == 25:
            # confirmed before placed!
            confirmed_dt = placed_dt - timedelta(seconds=2.0)
            fill_dt = placed_dt + timedelta(seconds=1.0)
        else:
            confirmed_dt = placed_dt + timedelta(seconds=random.uniform(0.05, 0.8))
            fill_dt = confirmed_dt + timedelta(seconds=random.uniform(0.2, 3.5))
            
        # 3. Off-market hours fill (e.g. 02:15 AM)
        if i == 35:
            fill_dt = fill_dt.replace(hour=2, minute=15)

        # Status and fill details
        rand_val = random.random()
        if rand_val < 0.75:
            status = "FILLED"
            fill_qty = qty
            reject_reason = "NONE"
            # 4. Out-of-band price deviation (> 5% slippage anomaly)
            if i == 45:
                fill_price = round(sig_price * 1.08, 2)  # 8% away
            else:
                slippage_mult = random.uniform(0.999, 1.003) if side == "BUY" else random.uniform(0.997, 1.001)
                fill_price = round(sig_price * slippage_mult, 2)
        elif rand_val < 0.88:
            status = "PARTIAL"
            fill_qty = int(qty * random.choice([0.2, 0.4, 0.5, 0.75]))
            reject_reason = "NONE"
            fill_price = round(sig_price * random.uniform(0.998, 1.002), 2)
            # 5. Over-fill quantity anomaly
            if i == 55:
                fill_qty = qty + 150
        else:
            status = "REJECTED"
            fill_qty = 0
            fill_price = None
            fill_dt = None
            reject_reason = random.choice(["EXCHANGE_THROTTLE", "INSUFFICIENT_MARGIN", "LIMIT_PRICE_OUT_OF_BOUNDS"])

        orders.append({
            "order_id": ord_id,
            "signal_id": assoc_sig_id,
            "order_placed_ts": placed_dt.isoformat(),
            "order_confirmed_ts": confirmed_dt.isoformat(),
            "fill_ts": fill_dt.isoformat() if fill_dt else "",
            "fill_price": fill_price if fill_price is not None else "",
            "fill_qty": fill_qty,
            "status": status,
            "reject_reason": reject_reason
        })

    return pd.DataFrame(signals), pd.DataFrame(orders)

def run_ingestion(raw_dir="data/raw"):
    os.makedirs(raw_dir, exist_ok=True)
    
    print("Fetching market data via yfinance...")
    mkt_df = fetch_market_prices()
    mkt_path = os.path.join(raw_dir, "market_prices.csv")
    mkt_df.to_csv(mkt_path, index=False)
    print(f"Saved market prices to {mkt_path} ({len(mkt_df)} rows)")
    
    print("Generating synthetic signal and order logs...")
    sig_df, ord_df = generate_synthetic_logs(mkt_df)
    
    sig_path = os.path.join(raw_dir, "signals.csv")
    ord_path = os.path.join(raw_dir, "orders.csv")
    
    sig_df.to_csv(sig_path, index=False)
    ord_df.to_csv(ord_path, index=False)
    
    print(f"Saved signals to {sig_path} ({len(sig_df)} rows)")
    print(f"Saved orders to {ord_path} ({len(ord_df)} rows)")

if __name__ == "__main__":
    run_ingestion()
