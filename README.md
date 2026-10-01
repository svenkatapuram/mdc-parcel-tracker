# Miami-Dade parcel change tracker

Keeps a history of changes to Miami-Dade County parcel records and shows them on a map with a time slider.

The county's [Property Boundary View](https://gis-mdc.opendata.arcgis.com/datasets/ed0468f5e579464b84727a4ab614fd40_0) layer only holds the current state of each parcel, so this project takes its own snapshots and records the differences between them.

## How it works

A GitHub Actions workflow (`.github/workflows/snapshot.yml`) runs daily:

1. It checks the layer's `dataLastEditDate` and stops if the county hasn't published anything new.
2. It pulls every parcel's tracked fields plus its center point, then finds the zoning district containing that point using the county's [Municipal Zone](https://opendata.miamidade.gov/datasets/municipal-zone) layer.
3. It compares the pull with the previous snapshot by folio and writes every change to the database.
4. It fetches the shapes of the changed parcels and adds them to the map data in `docs/data/`.

Changes are dated by the county's publish date, not the date the job ran.

### Tracked fields

| Group | Fields |
|---|---|
| Address | `TRUE_SITE_ADDR`, `TRUE_SITE_UNIT`, `TRUE_SITE_ZIP_CODE` |
| Owner | `TRUE_OWNER1`, `TRUE_OWNER2`, `TRUE_OWNER3` |
| Building | `BEDROOM_COUNT`, `BATHROOM_COUNT`, `HALF_BATHROOM_COUNT`, `FLOOR_COUNT`, `UNIT_COUNT`, `BUILDING_ACTUAL_AREA`, `BUILDING_HEATED_AREA`, `LOT_SIZE` |
| Value | `ASSESSMENT_YEAR_CUR`, `ASSESSED_VAL_CUR` |
| Sale | `DOS_1`, `PRICE_1` |
| Land use | `DOR_CODE_CUR`, `DOR_DESC` |
| Zoning | `ZONE`, `ZONE_DESC`, `MUNICIPALITY` (joined from Municipal Zone) |

Edit `tracker/config.py` to change the list. Parcels that appear or disappear are recorded with the field `PARCEL`.

### Safety checks

- Rows without a folio (about 5,000) are skipped. When a folio has several polygons, the largest one is used.
- The run aborts if the county republishes the layer mid-pull, or if the new pull has fewer than 90% of the previous parcels (a partial load).
- When one field changes on more than 25,000 parcels in a run (for example the yearly assessment roll), every change is still stored in the database, but that field is left off the map.

## The database

`parcels.db` is a SQLite file. It's too large to commit, so the workflow keeps it as a gzipped asset on a release named `database` and replaces it after each run.

| Table | Contents |
|---|---|
| `parcels` | One row per folio ever seen, with its latest values, `first_seen`, `last_seen` and `removed_on` |
| `changes` | One row per field change: `date`, `folio`, `field`, `old_value`, `new_value` |
| `runs` | One row per snapshot taken |

```sh
gh release download database -p parcels.db.gz && gunzip parcels.db.gz
sqlite3 parcels.db
```

```sql
-- Full history of one parcel
SELECT date, field, old_value, new_value FROM changes WHERE folio = '3059010240130' ORDER BY date;

-- Ownership changes in the last 30 days
SELECT date, folio, old_value, new_value FROM changes
WHERE field = 'TRUE_OWNER1' AND date >= date('now', '-30 day');

-- Zoning changes by new district
SELECT new_value AS zone, count(*) FROM changes WHERE field = 'ZONE' GROUP BY 1 ORDER BY 2 DESC;
```

## The map

`docs/` is a static MapLibre page on a CARTO Dark Matter base map, with a satellite option. Each run's changed parcels are colored by type of change. The slider steps through the dates, and clicking a parcel shows its timeline. Serve it with GitHub Pages: Settings, then Pages, then deploy from the `main` branch's `/docs` folder.

## Running locally

```sh
pip install -r requirements.txt
python -m tracker.run --db state/parcels.db    # add --force to snapshot even if nothing changed
python -m unittest discover -s tests -t .
```
