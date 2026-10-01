"""SQLite storage: current parcel state, the change history, and runs.

Tables
  parcels  one row per folio ever seen, holding its latest values
           (removed_on is set when a folio disappears from the county layer)
  changes  one row per field change: date, folio, field, old_value, new_value
  runs     one row per snapshot taken
"""

import json
import sqlite3

from .config import COLUMNS, PARCEL_EVENT

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    source_edit_ms INTEGER NOT NULL,
    ran_at TEXT NOT NULL,
    parcels INTEGER NOT NULL,
    changes INTEGER NOT NULL,
    parcels_changed INTEGER NOT NULL,
    mapped INTEGER NOT NULL,
    bulk TEXT NOT NULL,
    baseline INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS parcels (
    folio TEXT PRIMARY KEY,
    {", ".join(f"{c} TEXT NOT NULL DEFAULT ''" for c in COLUMNS)},
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    removed_on TEXT
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    date TEXT NOT NULL,
    folio TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT NOT NULL,
    new_value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS changes_folio ON changes(folio, date);
CREATE INDEX IF NOT EXISTS changes_date_field ON changes(date, field);
"""


def connect(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    # Columns added to config after the database was created.
    have = {r[1] for r in con.execute("PRAGMA table_info(parcels)")}
    for c in COLUMNS:
        if c not in have:
            con.execute(f"ALTER TABLE parcels ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
    return con


def has_baseline(con):
    return con.execute("SELECT 1 FROM runs LIMIT 1").fetchone() is not None


def load_current(con):
    """{folio: {column: value}} for parcels present in the last snapshot."""
    cur = con.execute(f"SELECT folio, {', '.join(COLUMNS)} FROM parcels WHERE removed_on IS NULL")
    return {r[0]: dict(zip(COLUMNS, r[1:])) for r in cur}


def save_run(con, run, snapshot, events):
    """Record a run, its changes, and the new current state, in one transaction."""
    date = run["date"]
    with con:
        run_id = con.execute(
            "INSERT INTO runs (date, source_edit_ms, ran_at, parcels, changes, parcels_changed, mapped, bulk, baseline)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date, run["source_edit_ms"], run["ran_at"], run["parcels"], run["changes"],
             run["parcels_changed"], run["mapped"], json.dumps(run["bulk"]), int(run["baseline"])),
        ).lastrowid
        con.executemany(
            "INSERT INTO changes (run_id, date, folio, field, old_value, new_value) VALUES (?, ?, ?, ?, ?, ?)",
            ((run_id, date, *e) for e in events),
        )
        cols = ", ".join(COLUMNS)
        marks = ", ".join("?" for _ in COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in COLUMNS)
        con.executemany(
            f"INSERT INTO parcels (folio, {cols}, first_seen, last_seen, removed_on) VALUES (?, {marks}, ?, ?, NULL)"
            f" ON CONFLICT(folio) DO UPDATE SET {updates}, last_seen = excluded.last_seen, removed_on = NULL",
            ((folio, *(row[c] for c in COLUMNS), date, date) for folio, row in snapshot.items()),
        )
        con.executemany(
            "UPDATE parcels SET removed_on = ? WHERE folio = ?",
            ((date, folio) for folio, field, _, new in events if field == PARCEL_EVENT and new == "removed"),
        )
    return run_id


def runs_for_map(con):
    cur = con.execute(
        "SELECT date, source_edit_ms, ran_at, parcels, changes, parcels_changed, mapped, bulk, baseline"
        " FROM runs ORDER BY id"
    )
    keys = ["date", "source_edit_ms", "ran_at", "parcels", "changes", "parcels_changed", "mapped", "bulk", "baseline"]
    out = []
    for r in cur:
        d = dict(zip(keys, r))
        d["bulk"], d["baseline"] = json.loads(d["bulk"]), bool(d["baseline"])
        out.append(d)
    return out

