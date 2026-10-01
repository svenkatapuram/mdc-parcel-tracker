"""Take a snapshot of the parcel layer, diff it against the last one, and
store the changes in the database and the map data.

    python -m tracker.run --db state/parcels.db
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import arcgis, db, mapdata
from .config import (BULK_THRESHOLD, KEY_FIELD, MIN_ROW_RATIO, PARCEL_FIELDS, PARCELS_LAYER,
                     ZONING_FIELDS, ZONING_LAYER)
from .geometry import ZoneIndex, esri_to_shape
from .snapshot import build_snapshot, bulk_fields, diff, is_bulk


def log(msg):
    print(msg, flush=True)


def load_zones():
    feats = arcgis.query_all(ZONING_LAYER, list(ZONING_FIELDS), geometry=True)
    return ZoneIndex([(esri_to_shape(f.get("geometry")), f["attributes"]) for f in feats])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="state/parcels.db", help="SQLite database (created on the first run)")
    ap.add_argument("--docs", default="docs", help="map viewer directory")
    ap.add_argument("--force", action="store_true", help="run even if the layer has not changed")
    ap.add_argument("--rebaseline", action="store_true",
                    help="allow starting over when earlier runs exist but the database is missing")
    args = ap.parse_args(argv)

    db_path, map_dir = Path(args.db), Path(args.docs) / "data"
    map_dir.mkdir(parents=True, exist_ok=True)
    runs_path, features_path = map_dir / "runs.json", map_dir / "changes.geojson"
    published_runs = mapdata.load_json(runs_path, [])

    if published_runs and not db_path.exists() and not args.rebaseline:
        log(f"Earlier runs exist but {db_path} is missing; refusing to start a new baseline "
            "(pass --rebaseline to do it anyway).")
        return 1

    edit_ms = arcgis.data_last_edit(PARCELS_LAYER)
    if published_runs and published_runs[-1]["source_edit_ms"] == edit_ms and not args.force:
        log("Parcel layer unchanged since the last run; nothing to do.")
        return 0

    date = dt.datetime.fromtimestamp(edit_ms / 1000, dt.timezone.utc).date().isoformat()
    log(f"Parcel layer last edited {date}; loading zoning districts...")
    zones = load_zones()
    log(f"{len(zones.zones)} zoning districts. Pulling parcels...")
    features = list(arcgis.query_all(PARCELS_LAYER, [KEY_FIELD, "Shape__Area", *PARCEL_FIELDS], centroid=True))
    if arcgis.data_last_edit(PARCELS_LAYER) != edit_ms:
        log("The county updated the layer during the pull; try again later.")
        return 1
    snapshot = build_snapshot(features, zones)
    log(f"{len(features)} rows, {len(snapshot)} parcels with a folio.")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = db.connect(db_path)
    baseline = not db.has_baseline(con)
    run = {
        "date": date,
        "source_edit_ms": edit_ms,
        "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "parcels": len(snapshot),
        "changes": 0,
        "parcels_changed": 0,
        "mapped": 0,
        "bulk": {},
        "baseline": baseline,
    }

    events, feats = [], []
    if not baseline:
        previous = db.load_current(con)
        if len(snapshot) < MIN_ROW_RATIO * len(previous):
            log(f"Only {len(snapshot)} parcels against {len(previous)} last time; "
                "looks like a partial load, not diffing.")
            return 1
        events = diff(previous, snapshot)
        bulk = bulk_fields(events, BULK_THRESHOLD)
        map_events = [e for e in events if not is_bulk(e, bulk)]
        changed = {e[0] for e in map_events if e[3] != "removed"}
        log(f"{len(events)} changes on {len({e[0] for e in events})} parcels; fetching shapes for {len(changed)}"
            + (f" (county-wide updates left off the map: {bulk})" if bulk else ""))
        feats = mapdata.build_features(map_events, snapshot, mapdata.fetch_geometries(changed), date)
        run.update(changes=len(events), parcels_changed=len({e[0] for e in events}),
                   mapped=len(feats), bulk=bulk)

    db.save_run(con, run, snapshot, events)
    mapdata.append_features(features_path, feats)
    mapdata.write_json(runs_path, db.runs_for_map(con))
    con.close()
    log("Baseline snapshot saved; changes appear from the next county update." if baseline else "Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
