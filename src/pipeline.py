import os
import sys
import argparse
import logging
import pandas as pd

# Fix Windows console UTF-8 encoding if needed
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure root workspace directory is in sys.path for IDE linting & script execution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ingest import run_ingestion
from src.validate import validate_pipeline_data
from src.model import build_workflow_model
from src.metrics import compute_execution_metrics

# Configure logging to both console and pipeline.log
def setup_logger(log_file="pipeline.log"):
    logger = logging.getLogger("execution_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers = []  # clear existing handlers
    
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
    
    # File handler
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    return logger

def print_formatted_evidence_table(df):
    if df.empty:
        print("No metrics computed.")
        return

    # Set pandas display options to prevent line wrapping in terminals
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)
    pd.set_option("display.colheader_justify", "right")

    disp_df = df.copy()
    disp_df = disp_df.rename(columns={
        "symbol": "Symbol",
        "total_orders": "Orders",
        "filled_orders": "Filled",
        "partial_orders": "Partial",
        "rejected_orders": "Rejected",
        "fill_rate_pct": "Fill %",
        "partial_rate_pct": "Part %",
        "rejection_rate_pct": "Rej %",
        "median_latency_sec": "Med Lat (s)",
        "p95_latency_sec": "p95 Lat (s)",
        "avg_slippage_bps": "Slip (bps)",
        "total_slippage_cost_inr": "Slippage (INR)",
        "top_rejection_reason": "Top Reject Reason"
    })
    
    disp_df["Slippage (INR)"] = disp_df["Slippage (INR)"].apply(lambda x: f"INR {x:,.2f}")
    disp_df["Fill %"] = disp_df["Fill %"].apply(lambda x: f"{x:.1f}%")
    disp_df["Part %"] = disp_df["Part %"].apply(lambda x: f"{x:.1f}%")
    disp_df["Rej %"] = disp_df["Rej %"].apply(lambda x: f"{x:.1f}%")

    border = "=" * 135
    print("\n" + border)
    print("                                      FINAL EXECUTION QUALITY EVIDENCE TABLE                                      ")
    print(border)
    print(disp_df.to_string(index=False))
    print(border + "\n")

def run_pipeline(dry_run=False, raw_dir="data/raw", processed_dir="data/processed"):
    logger = setup_logger()
    logger.info("=== Starting Execution Quality Data Pipeline ===")
    if dry_run:
        logger.info("[DRY RUN MODE ENABLED] - No output files will be persisted.")

    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)

    # 1. Ingestion Phase
    sig_path = os.path.join(raw_dir, "signals.csv")
    ord_path = os.path.join(raw_dir, "orders.csv")

    if not os.path.exists(sig_path) or not os.path.exists(ord_path):
        logger.info("Raw files missing. Initiating data ingestion...")
        try:
            run_ingestion(raw_dir=raw_dir)
        except Exception as e:
            logger.error(f"Failed to ingest raw data: {e}. Exiting pipeline.")
            return

    # Load raw data with error handling
    try:
        sig_df = pd.read_csv(sig_path)
        ord_df = pd.read_csv(ord_path)
        logger.info(f"Loaded raw signals ({len(sig_df)} rows) and raw orders ({len(ord_df)} rows).")
    except Exception as e:
        logger.error(f"Error reading raw CSV files: {e}")
        return

    # 2. Validation Phase
    logger.info("Running business rule validation checks...")
    clean_sig, clean_ord, val_report = validate_pipeline_data(sig_df, ord_df)
    
    num_violations = len(val_report) if not val_report.empty else 0
    logger.info(f"Validation completed. Total rule violations flagged: {num_violations}")
    
    if num_violations > 0:
        breakdown = val_report["rule_failed"].value_counts().to_dict()
        logger.info(f"Violation summary: {breakdown}")

    if not dry_run:
        val_report_path = os.path.join(processed_dir, "validation_report.csv")
        val_report.to_csv(val_report_path, index=False)
        logger.info(f"Saved validation report to {val_report_path}")

    # 3. Workflow Modeling Phase
    logger.info("Building relational execution model...")
    db_path = os.path.join(processed_dir, "execution_warehouse.db")
    
    if dry_run:
        db_path = ":memory:"

    model_df = build_workflow_model(clean_sig, clean_ord, db_path=db_path)
    logger.info(f"Execution model joined {len(model_df)} valid transaction records.")

    # 4. Metrics Computation Phase
    logger.info("Calculating execution quality KPIs & evidence table...")
    evidence_df = compute_execution_metrics(model_df)

    if not dry_run:
        evidence_path = os.path.join(processed_dir, "evidence_table.csv")
        evidence_df.to_csv(evidence_path, index=False)
        logger.info(f"Saved evidence table to {evidence_path}")

    # Print clean formatted summary to console
    print_formatted_evidence_table(evidence_df)

    logger.info("=== Execution Pipeline Completed Successfully ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Order-to-Fill Execution Quality Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Validate and calculate without writing output files")
    args = parser.parse_args()
    
    run_pipeline(dry_run=args.dry_run)
