"""Minimal ArcGIS REST feature-service client (stdlib only)."""

import json
import time
import urllib.parse
import urllib.request

PAGE_SIZE = 2000


def _request(url, params, retries=4):
    data = urllib.parse.urlencode({**params, "f": "json"}).encode()
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "mdc-parcel-tracker"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.load(resp)
            if "error" in body:
                raise RuntimeError(f"ArcGIS error from {url}: {body['error']}")
            return body
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 ** (attempt + 1))


def layer_info(layer_url):
    return _request(layer_url, {})


def data_last_edit(layer_url):
    """Epoch milliseconds of the layer's last data edit."""
    return layer_info(layer_url)["editingInfo"]["dataLastEditDate"]


def query_all(layer_url, out_fields, where="1=1", geometry=False, centroid=False, out_sr=4326):
    """Yield every feature matching `where`, paging by OBJECTID."""
    last_oid = -1
    while True:
        params = {
            "where": f"({where}) AND OBJECTID > {last_oid}",
            "outFields": ",".join(["OBJECTID", *out_fields]),
            "orderByFields": "OBJECTID",
            "resultRecordCount": PAGE_SIZE,
            "returnGeometry": str(geometry).lower(),
            "outSR": out_sr,
        }
        if geometry:
            params["geometryPrecision"] = 6
        if centroid:
            params["returnCentroid"] = "true"
        features = _request(f"{layer_url}/query", params).get("features", [])
        if not features:
            return
        yield from features
        last_oid = features[-1]["attributes"]["OBJECTID"]
