"""Write the map viewer's data files (docs/data)."""

import json
from collections import defaultdict
from pathlib import Path

from shapely.ops import unary_union

from . import arcgis
from .config import CATEGORIES, CATEGORY_PRIORITY, KEY_FIELD, LABELS, PARCEL_EVENT, PARCELS_LAYER
from .geometry import esri_to_shape, to_geojson

BATCH = 150


def fetch_geometries(folios, layer_url=PARCELS_LAYER):
    """Return {folio: shapely geometry} for the given folios (WGS84)."""
    parts = defaultdict(list)
    folios = sorted(folios)
    for i in range(0, len(folios), BATCH):
        quoted = ",".join("'" + f.replace("'", "''") + "'" for f in folios[i : i + BATCH])
        for feat in arcgis.query_all(layer_url, [KEY_FIELD], where=f"{KEY_FIELD} IN ({quoted})", geometry=True):
            shape = esri_to_shape(feat.get("geometry"))
            if shape is not None:
                parts[feat["attributes"][KEY_FIELD]].append(shape)
    return {f: (s[0] if len(s) == 1 else unary_union(s)) for f, s in parts.items()}


def event_category(field, new):
    if field == PARCEL_EVENT:
        return "new" if new == "added" else "removed"
    return CATEGORIES[field]


def build_features(events, snapshot, geometries, date):
    """One GeoJSON feature per changed parcel for this run's date (YYYY-MM-DD)."""
    by_folio = defaultdict(list)
    for folio, field, old, new in events:
        by_folio[folio].append((field, old, new))

    features = []
    for folio in sorted(by_folio):
        shape = geometries.get(folio)
        if shape is None:  # removed parcels have no current geometry
            continue
        evs = by_folio[folio]
        cats = {event_category(f, n) for f, _, n in evs}
        primary = next(c for c in CATEGORY_PRIORITY if c in cats)
        row = snapshot.get(folio, {})
        addr = " ".join(x for x in (row.get("TRUE_SITE_ADDR", ""), row.get("TRUE_SITE_UNIT", "")) if x)
        features.append({
            "type": "Feature",
            "geometry": to_geojson(shape),
            "properties": {
                "folio": folio,
                "date": date,
                "cat": primary,
                "cats": ",".join(c for c in CATEGORY_PRIORITY if c in cats),
                "addr": addr,
                "ev": json.dumps([[LABELS[f], o, n] for f, o, n in evs], separators=(",", ":")),
            },
        })
    return features


def load_json(path, default):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


def append_features(path, features):
    fc = load_json(path, {"type": "FeatureCollection", "features": []})
    fc["features"].extend(features)
    Path(path).write_text(json.dumps(fc, separators=(",", ":")))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=1) + "\n")
