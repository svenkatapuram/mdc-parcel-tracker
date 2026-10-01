import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tracker import arcgis, run
from tracker.config import PARCELS_LAYER, ZONING_LAYER


def square(x, y, size=1.0):
    # Esri outer rings run clockwise.
    return {"rings": [[[x, y], [x, y + size], [x + size, y + size], [x + size, y], [x, y]]]}


def parcel(oid, folio, x, y, **attrs):
    base = {"OBJECTID": oid, "FOLIO": folio, "Shape__Area": 1.0, "TRUE_SITE_ADDR": f"{oid} MAIN ST",
            "TRUE_OWNER1": "OWNER A", "ASSESSED_VAL_CUR": 100000.0, "BATHROOM_COUNT": 2.0}
    base.update(attrs)
    return {"attributes": base, "centroid": {"x": x + 0.5, "y": y + 0.5}, "geometry": square(x, y)}


ZONES = [
    {"attributes": {"OBJECTID": 1, "ZONE": "RU-1", "ZONEDESC": "Single family", "MUNICNAME": "UNINCORPORATED"},
     "geometry": square(0, 0, 10)},
    {"attributes": {"OBJECTID": 2, "ZONE": "BU-2", "ZONEDESC": "Business", "MUNICNAME": "DORAL"},
     "geometry": square(10, 0, 10)},
]


class FakeService:
    def __init__(self, parcels, edit_ms):
        self.parcels, self.edit_ms = parcels, edit_ms

    def data_last_edit(self, url):
        return self.edit_ms

    def query_all(self, url, out_fields, where="1=1", geometry=False, centroid=False, out_sr=4326):
        if url == ZONING_LAYER:
            return list(ZONES)
        assert url == PARCELS_LAYER
        feats = self.parcels
        m = re.match(r"FOLIO IN \((.*)\)", where)
        if m:
            wanted = set(re.findall(r"'([^']*)'", m.group(1)))
            feats = [f for f in feats if f["attributes"]["FOLIO"] in wanted]
        return [{"attributes": f["attributes"], **({"centroid": f["centroid"]} if centroid else {}),
                 **({"geometry": f["geometry"]} if geometry else {})} for f in feats]


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "state" / "parcels.db"
        self.docs = self.tmp / "docs"

    def run_with(self, service, *extra):
        with mock.patch.object(arcgis, "query_all", service.query_all), \
             mock.patch.object(arcgis, "data_last_edit", service.data_last_edit):
            return run.main(["--db", str(self.db), "--docs", str(self.docs), *extra])

    def runs(self):
        return json.loads((self.docs / "data" / "runs.json").read_text())

    def features(self):
        return json.loads((self.docs / "data" / "changes.geojson").read_text())["features"]

    def changes(self):
        con = sqlite3.connect(self.db)
        return con.execute("SELECT date, folio, field, old_value, new_value FROM changes ORDER BY folio, field").fetchall()

    def baseline(self):
        parcels = [parcel(1, "0100", 1, 1), parcel(2, "0200", 3, 3), parcel(3, "0300", 12, 1),
                   parcel(4, None, 5, 5),  # no folio: skipped
                   parcel(5, "0200", 3, 6, Shape__Area=0.5)]  # smaller duplicate polygon: ignored
        self.assertEqual(self.run_with(FakeService(parcels, 1790725621644)), 0)
        return parcels

    def test_baseline_then_changes(self):
        parcels = self.baseline()
        self.assertTrue(self.runs()[0]["baseline"])
        self.assertEqual(self.runs()[0]["parcels"], 3)
        self.assertEqual(self.features(), [])
        self.assertEqual(self.changes(), [])

        # Same edit date: skipped.
        self.assertEqual(self.run_with(FakeService(parcels, 1790725621644)), 0)
        self.assertEqual(len(self.runs()), 1)

        changed = [
            parcel(1, "0100", 1, 1, TRUE_OWNER1="OWNER B", DOS_1="2026-09-30", PRICE_1=550000.0),
            parcel(2, "0200", 13, 3),                       # now falls in the Doral BU-2 district
            parcel(5, "0200", 3, 6, Shape__Area=0.5),
            parcel(6, "0400", 4, 4),                        # new parcel; 0300 removed
        ]
        self.assertEqual(self.run_with(FakeService(changed, 1790812021644)), 0)

        self.assertEqual(self.changes(), [
            ("2026-09-30", "0100", "DOS_1", "", "2026-09-30"),
            ("2026-09-30", "0100", "PRICE_1", "", "550000"),
            ("2026-09-30", "0100", "TRUE_OWNER1", "OWNER A", "OWNER B"),
            ("2026-09-30", "0200", "MUNICIPALITY", "UNINCORPORATED", "DORAL"),
            ("2026-09-30", "0200", "ZONE", "RU-1", "BU-2"),
            ("2026-09-30", "0200", "ZONE_DESC", "Single family", "Business"),
            ("2026-09-30", "0300", "PARCEL", "existing", "removed"),
            ("2026-09-30", "0400", "PARCEL", "", "added"),
        ])
        feats = {f["properties"]["folio"]: f["properties"] for f in self.features()}
        self.assertEqual(set(feats), {"0100", "0200", "0400"})  # removed parcel has no shape
        self.assertEqual(feats["0100"]["cat"], "owner")
        self.assertEqual(feats["0100"]["cats"], "owner,sale")
        self.assertEqual(feats["0200"]["cat"], "zoning")
        self.assertEqual(feats["0400"]["cat"], "new")
        self.assertIn(["Owner 1", "OWNER A", "OWNER B"], json.loads(feats["0100"]["ev"]))

        run2 = self.runs()[-1]
        self.assertEqual((run2["changes"], run2["parcels_changed"], run2["mapped"]), (8, 4, 3))

        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT removed_on FROM parcels WHERE folio='0300'").fetchone(), ("2026-09-30",))
        self.assertEqual(con.execute("SELECT TRUE_OWNER1 FROM parcels WHERE folio='0100'").fetchone(), ("OWNER B",))

    def test_bulk_updates_stay_off_the_map(self):
        parcels = self.baseline()
        reassessed = [{**f, "attributes": {**f["attributes"], "ASSESSED_VAL_CUR": 120000.0}} for f in parcels]
        reassessed[0]["attributes"]["TRUE_OWNER1"] = "OWNER C"
        with mock.patch.object(run, "BULK_THRESHOLD", 2):
            self.assertEqual(self.run_with(FakeService(reassessed, 1790812021644)), 0)
        self.assertEqual(self.runs()[-1]["bulk"], {"ASSESSED_VAL_CUR": 3})
        self.assertEqual(len([c for c in self.changes() if c[2] == "ASSESSED_VAL_CUR"]), 3)
        feats = self.features()
        self.assertEqual([f["properties"]["folio"] for f in feats], ["0100"])
        self.assertEqual(json.loads(feats[0]["properties"]["ev"]), [["Owner 1", "OWNER A", "OWNER C"]])

    def test_partial_load_is_refused(self):
        self.baseline()
        self.assertEqual(self.run_with(FakeService([parcel(1, "0100", 1, 1)], 1790812021644)), 1)
        self.assertEqual(len(self.runs()), 1)

    def test_missing_database_is_refused(self):
        parcels = self.baseline()
        self.db.unlink()
        self.assertEqual(self.run_with(FakeService(parcels, 1790812021644)), 1)
        self.assertEqual(self.run_with(FakeService(parcels, 1790812021644), "--rebaseline"), 0)


if __name__ == "__main__":
    unittest.main()
