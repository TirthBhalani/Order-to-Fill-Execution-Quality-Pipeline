"""Notebook-facing helpers for the FlashEats challenge workspace.

This file is intentionally lightweight and resilient: it is designed to work from the
challenge-local data directory while remaining tolerant of missing processed snapshots.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
RUN_DATE = "2026-09-27"


def load_context() -> dict:
    """Load key challenge data and optional processed artifacts when available."""
    database = RAW / "flasheats.db"
    result: dict[str, object] = {}

    if database.exists():
        with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as con:
            for name in ("orders", "customers", "drivers", "restaurants"):
                if name in _table_names(con):
                    result[name] = pd.read_sql_query(f'SELECT * FROM "{name}"', con)

    for name in (
        "support_tickets",
        "restaurant_status",
        "customer_app_actions",
        "customer_interactions",
        "order_events",
        "order_interventions",
        "order_outcomes",
        "restaurants",
    ):
        csv_path = RAW / f"{name}.csv"
        if csv_path.exists():
            result[name] = pd.read_csv(csv_path)

    driver_events_path = RAW / "driver_events.json"
    if driver_events_path.exists():
        with driver_events_path.open("r", encoding="utf-8") as handle:
            result["driver_events"] = json.load(handle)

    metric_defs_path = RAW / "client_metric_definitions.json"
    if metric_defs_path.exists():
        with metric_defs_path.open("r", encoding="utf-8") as handle:
            result["metric_definitions"] = json.load(handle)

    brief_path = RAW / "class7_model_brief.json"
    if brief_path.exists():
        with brief_path.open("r", encoding="utf-8") as handle:
            result["model_brief"] = json.load(handle)

    journey_path = PROCESSED / "order_journey.jsonl"
    if journey_path.exists():
        result["journey"] = pd.read_json(journey_path, lines=True)
    else:
        result["journey"] = pd.DataFrame()

    for name in ("metrics", "quality_report", "cleaning_report", "run_manifest"):
        candidate = PROCESSED / f"{name}.json"
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as handle:
                result[name] = json.load(handle)

    return result


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    ).fetchall()
    return {row[0] for row in rows}


def lateness_view(journey: pd.DataFrame) -> pd.DataFrame:
    """Create the canonical order-level late-delivery view from a snapshot of journey data."""
    if journey.empty:
        return pd.DataFrame()

    frame = journey.copy()
    for column in ("created_at", "promised_eta", "pickup_at", "actual_delivery_at"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], format="mixed", errors="coerce")

    if "actual_delivery_at" in frame.columns and "promised_eta" in frame.columns:
        frame["delay_min"] = (
            frame["actual_delivery_at"] - frame["promised_eta"]
        ).dt.total_seconds() / 60
    else:
        frame["delay_min"] = pd.NA

    if {"final_status", "promised_eta", "actual_delivery_at", "delay_min"}.issubset(frame.columns):
        frame["ldr_eligible"] = (
            frame["final_status"].eq("delivered")
            & frame["promised_eta"].notna()
            & frame["actual_delivery_at"].notna()
            & frame["delay_min"].notna()
        )
        frame["late"] = frame["ldr_eligible"] & frame["delay_min"].gt(0)
        frame["late_10"] = frame["ldr_eligible"] & frame["delay_min"].gt(10)
    else:
        frame["ldr_eligible"] = pd.Series(False, index=frame.index)
        frame["late"] = pd.Series(False, index=frame.index)
        frame["late_10"] = pd.Series(False, index=frame.index)

    return frame


def normalize_ticket_category(series: pd.Series) -> pd.Series:
    """Normalize the most common documented category variants without forcing semantics."""
    normalized = series.astype("string").str.strip().str.lower().str.replace(" ", "_", regex=False)
    return normalized.replace({"eta_issue": "eta_issue", "late_delivery": "late_delivery"})


def class7_order_model(context: dict) -> pd.DataFrame:
    """Create an order-level model that aggregates one-to-many inputs before joining."""
    journey = lateness_view(context.get("journey", pd.DataFrame()))
    tickets = context.get("support_tickets", pd.DataFrame())
    actions = context.get("customer_app_actions", pd.DataFrame())
    interventions = context.get("order_interventions", pd.DataFrame())

    if journey.empty:
        return pd.DataFrame()

    support = (
        tickets.dropna(subset=["order_id"]).groupby("order_id").size()
        .rename("support_ticket_count").reset_index()
    )
    cancel = (
        actions.assign(cancel_attempted=actions.action_type.eq("CANCEL_ATTEMPTED"))
        .groupby("order_id", as_index=False)["cancel_attempted"].max()
    )
    intervention = (
        interventions.groupby("order_id").agg(
            intervention_count=("intervention_id", "count"),
            intervention_types=("intervention_type", lambda values: tuple(sorted(set(values)))),
        ).reset_index()
    )

    model = journey[[
        "order_id",
        "customer_id",
        "restaurant_id",
        "final_status",
        "delay_min",
        "ldr_eligible",
        "late",
        "late_10",
    ]].copy()
    model = model.merge(support, on="order_id", how="left", validate="one_to_one")
    model = model.merge(cancel, on="order_id", how="left", validate="one_to_one")
    model = model.merge(intervention, on="order_id", how="left", validate="one_to_one")

    model["support_ticket_count"] = model.support_ticket_count.fillna(0).astype(int)
    model["support_opened"] = model.support_ticket_count.gt(0)
    model["cancel_attempted"] = model.cancel_attempted.fillna(False).astype(bool)
    model["intervention_count"] = model.intervention_count.fillna(0).astype(int)
    model["intervention_types"] = model.intervention_types.map(
        lambda value: value if isinstance(value, tuple) else tuple()
    )
    model["late_flag"] = model["late"].where(model["ldr_eligible"], pd.NA).astype("boolean")
    return model


def build_order_timeline(order_id: str, context: dict) -> pd.DataFrame:
    """Union observed lifecycle records without inventing milestones that are absent."""
    rows: list[dict] = []

    def add(frame, time_col, type_col, actor, source):
        subset = frame.loc[frame.order_id.eq(order_id)]
        for row in subset.itertuples(index=False):
            rows.append({
                "event_time": getattr(row, time_col),
                "event_type": getattr(row, type_col),
                "actor": actor(row) if callable(actor) else actor,
                "source_system": source,
            })

    order_events = context.get("order_events", pd.DataFrame())
    app_actions = context.get("customer_app_actions", pd.DataFrame())
    tickets = context.get("support_tickets", pd.DataFrame()).dropna(subset=["order_id"])
    restaurant_status = context.get("restaurant_status", pd.DataFrame())
    interventions = context.get("order_interventions", pd.DataFrame())
    driver_events = context.get("driver_events", [])

    if not order_events.empty:
        add(order_events, "event_time", "event_type", lambda row: f"{row.actor_type}:{row.actor_id}", "order_events")
    if not app_actions.empty:
        add(app_actions, "action_at", "action_type", "customer", "customer_app")
    if not tickets.empty:
        add(tickets, "created_at", "category", "support/customer", "support")
    if not restaurant_status.empty:
        add(restaurant_status, "last_updated_at", "status", "restaurant", "restaurant_status")
    if not interventions.empty:
        add(interventions, "intervention_at", "intervention_type", lambda row: row.initiated_by, "interventions")

    for driver in driver_events:
        for event in driver.get("events", []):
            if event.get("order_id") == order_id:
                rows.append({
                    "event_time": event.get("timestamp"),
                    "event_type": event.get("type"),
                    "actor": f"driver:{driver.get('driver_id')}",
                    "source_system": "driver_telemetry",
                })

    timeline = pd.DataFrame(rows)
    if timeline.empty:
        return timeline

    timeline["event_time"] = pd.to_datetime(timeline["event_time"], format="mixed", errors="coerce")
    return timeline.sort_values(["event_time", "source_system", "event_type"], kind="stable").reset_index(drop=True)
