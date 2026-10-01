"""Esri JSON geometry -> shapely / GeoJSON, and point-in-zone lookup."""

from shapely import STRtree
from shapely.geometry import MultiPolygon, Point, Polygon, mapping


def esri_to_shape(geom):
    """Convert an Esri polygon ({"rings": [...]}) to a shapely geometry.

    Esri outer rings run clockwise and holes counter-clockwise; each hole is
    attached to the outer ring that contains it.
    """
    outers, holes = [], []
    for ring in (geom or {}).get("rings", []):
        if len(ring) < 4:
            continue
        poly = Polygon(ring)
        (holes if poly.exterior.is_ccw else outers).append(ring)
    if not outers:
        # Some publishers ignore ring orientation; treat every ring as an outer ring.
        outers, holes = holes, []
    shells = [[o, []] for o in outers]
    for hole in holes:
        pt = Point(hole[0])
        for shell in shells:
            if Polygon(shell[0]).contains(pt):
                shell[1].append(hole)
                break
    polys = [Polygon(o, hs) for o, hs in shells]
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def to_geojson(shape, precision=6):
    def rnd(coords):
        if isinstance(coords[0], (int, float)):
            return [round(c, precision) for c in coords]
        return [rnd(c) for c in coords]

    g = mapping(shape)
    return {"type": g["type"], "coordinates": rnd(g["coordinates"])}


class ZoneIndex:
    """Find the zoning district containing a point."""

    def __init__(self, zones):
        # zones: list of (shape, attributes)
        self.zones = [(s, a) for s, a in zones if s is not None and not s.is_empty]
        self.tree = STRtree([s for s, _ in self.zones])

    def lookup(self, x, y):
        hits = self.tree.query(Point(x, y), predicate="intersects")
        if len(hits) == 0:
            return None
        # Overlapping districts: pick the smallest, so the answer is stable.
        best = min(hits, key=lambda i: (self.zones[i][0].area, i))
        return self.zones[best][1]
