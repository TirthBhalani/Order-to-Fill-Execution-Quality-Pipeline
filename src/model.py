import os
import sys
import sqlite3
import pandas as pd

# Ensure root workspace directory is in sys.path for IDE linting & script execution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def build_workflow_model(sig_df, ord_df, db_path="data/processed/execution_warehouse.db"):
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    # Connect SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Create tables with foreign key constraints
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        signal_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        signal_price REAL NOT NULL,
        quantity INTEGER NOT NULL
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        order_placed_ts TEXT NOT NULL,
        order_confirmed_ts TEXT NOT NULL,
        fill_ts TEXT,
        fill_price REAL,
        fill_qty INTEGER NOT NULL,
        status TEXT NOT NULL,
        reject_reason TEXT,
        FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
    );
    """)
    
    # Clean old records for rerun idempotency
    cursor.execute("DELETE FROM orders;")
    cursor.execute("DELETE FROM signals;")
    conn.commit()
    
    # Insert clean signals and orders
    sig_df.to_sql("signals", conn, if_exists="append", index=False)
    ord_df.to_sql("orders", conn, if_exists="append", index=False)
    
    # 2. Construct unified event/execution dataset via JOIN query
    query = """
    SELECT 
        o.order_id,
        o.signal_id,
        s.symbol,
        s.side,
        s.timestamp AS signal_ts,
        s.signal_price,
        s.quantity AS order_qty,
        o.order_placed_ts,
        o.order_confirmed_ts,
        o.fill_ts,
        o.fill_price,
        o.fill_qty,
        o.status,
        o.reject_reason
    FROM orders o
    JOIN signals s ON o.signal_id = s.signal_id
    """
    
    model_df = pd.read_sql_query(query, conn)
    conn.close()
    
    return model_df

if __name__ == "__main__":
    from src.validate import validate_pipeline_data
    sig_df = pd.read_csv("data/raw/signals.csv")
    ord_df = pd.read_csv("data/raw/orders.csv")
    c_sig, c_ord, _ = validate_pipeline_data(sig_df, ord_df)
    m_df = build_workflow_model(c_sig, c_ord)
    print(f"Workflow model built successfully with {len(m_df)} execution records.")
