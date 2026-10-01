"""Build and compare parcel snapshots."""

from collections import Counter

from .config import COLUMNS, KEY_FIELD, PARCEL_EVENT, PARCEL_FIELDS, ZONING_FIELDS


def normalize(value):
    """Render a field value as a comparable string ('' for null)."""
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(round(value, 4))
    if isinstance(value, int):
        return str(value)
    return " ".join(str(value).split())


def build_snapshot(features, zone_index):
    """Return {folio: {column: value}} from parcel features.

    Rows without a folio are skipped. When a folio has several polygons, the
    largest one wins so the result does not depend on row order.
    """
    best = {}
    for feat in features:
        attrs = feat["attributes"]
        folio = normalize(attrs.get(KEY_FIELD))
        if not folio:
            continue
        area = attrs.get("Shape__Area") or 0
        if folio in best and best[folio][0] >= area:
            continue
        best[folio] = (area, feat)

    snapshot = {}
    for folio, (_, feat) in best.items():
        attrs = feat["attributes"]
        row = {f: normalize(attrs.get(f)) for f in PARCEL_FIELDS}
        centroid = feat.get("centroid")
        zone = zone_index.lookup(centroid["x"], centroid["y"]) if centroid else None
        for src, (col, _, _) in ZONING_FIELDS.items():
            row[col] = normalize(zone.get(src)) if zone else ""
        snapshot[folio] = row
    return snapshot


def diff(old, new):
    """Return change events as (folio, field, old_value, new_value) tuples."""
    events = []
    for folio in sorted(new.keys() - old.keys()):
        events.append((folio, PARCEL_EVENT, "", "added"))
    for folio in sorted(old.keys() - new.keys()):
        events.append((folio, PARCEL_EVENT, "existing", "removed"))
    for folio in sorted(new.keys() & old.keys()):
        a, b = old[folio], new[folio]
        for col in COLUMNS:
            if a.get(col, "") != b.get(col, ""):
                events.append((folio, col, a.get(col, ""), b.get(col, "")))
    return events


def bulk_fields(events, threshold):
    """Fields (and parcel adds/removes) that changed on more than `threshold` parcels."""
    counts = Counter(
        (f if f != PARCEL_EVENT else f"{PARCEL_EVENT}:{new}") for _, f, _, new in events
    )
    return {k: n for k, n in counts.items() if n > threshold}


def is_bulk(event, bulk):
    _, field, _, new = event
    key = field if field != PARCEL_EVENT else f"{PARCEL_EVENT}:{new}"
    return key in bulk
