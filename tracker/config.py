"""Sources, tracked fields and change categories."""

SERVICE_ROOT = "https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services"
PARCELS_LAYER = f"{SERVICE_ROOT}/PaParcelView_gdb/FeatureServer/0"
ZONING_LAYER = f"{SERVICE_ROOT}/MunicipalZone_gdb/FeatureServer/0"

KEY_FIELD = "FOLIO"

# Parcel-layer field -> (label, category)
PARCEL_FIELDS = {
    "TRUE_SITE_ADDR": ("Address", "address"),
    "TRUE_SITE_UNIT": ("Unit", "address"),
    "TRUE_SITE_ZIP_CODE": ("Zip code", "address"),
    "TRUE_OWNER1": ("Owner 1", "owner"),
    "TRUE_OWNER2": ("Owner 2", "owner"),
    "TRUE_OWNER3": ("Owner 3", "owner"),
    "BEDROOM_COUNT": ("Bedrooms", "building"),
    "BATHROOM_COUNT": ("Bathrooms", "building"),
    "HALF_BATHROOM_COUNT": ("Half baths", "building"),
    "FLOOR_COUNT": ("Floors", "building"),
    "UNIT_COUNT": ("Units", "building"),
    "BUILDING_ACTUAL_AREA": ("Actual area (sq ft)", "building"),
    "BUILDING_HEATED_AREA": ("Living area (sq ft)", "building"),
    "LOT_SIZE": ("Lot size", "building"),
    "ASSESSMENT_YEAR_CUR": ("Assessment year", "value"),
    "ASSESSED_VAL_CUR": ("Assessed value", "value"),
    "DOS_1": ("Last sale date", "sale"),
    "PRICE_1": ("Last sale price", "sale"),
    "DOR_CODE_CUR": ("DOR code", "landuse"),
    "DOR_DESC": ("DOR description", "landuse"),
}

# Zoning-layer field -> (snapshot column, label, category)
ZONING_FIELDS = {
    "ZONE": ("ZONE", "Zoning", "zoning"),
    "ZONEDESC": ("ZONE_DESC", "Zoning description", "zoning"),
    "MUNICNAME": ("MUNICIPALITY", "Municipality", "zoning"),
}

PARCEL_EVENT = "PARCEL"  # pseudo-field for parcels that appear or disappear

LABELS = {f: label for f, (label, _) in PARCEL_FIELDS.items()}
LABELS.update({col: label for col, label, _ in ZONING_FIELDS.values()})
LABELS[PARCEL_EVENT] = "Parcel"

CATEGORIES = {f: cat for f, (_, cat) in PARCEL_FIELDS.items()}
CATEGORIES.update({col: cat for col, _, cat in ZONING_FIELDS.values()})
CATEGORIES[PARCEL_EVENT] = "new"

# When a parcel has several kinds of change on one date, the map colors it by
# the first category in this list.
CATEGORY_PRIORITY = ["new", "zoning", "landuse", "owner", "sale", "building", "value", "address"]

# All snapshot columns, in a stable order.
COLUMNS = list(PARCEL_FIELDS) + [col for col, _, _ in ZONING_FIELDS.values()]

# A field that changes on more parcels than this in one run is a county-wide
# update (for example the yearly assessment roll). It is kept in the change log
# but left off the map, which would otherwise have to draw every parcel.
BULK_THRESHOLD = 25_000

# Refuse to diff when the new pull is much smaller than the last one; a partial
# load would otherwise show up as thousands of removed parcels.
MIN_ROW_RATIO = 0.9
