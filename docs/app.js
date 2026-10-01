const CATEGORIES = {
  new:      { label: "New parcel", color: "#ffffff" },
  zoning:   { label: "Zoning",     color: "#4cc9f0" },
  landuse:  { label: "Land use",   color: "#b388ff" },
  owner:    { label: "Owner",      color: "#ff6b6b" },
  sale:     { label: "Sale",       color: "#ffd166" },
  building: { label: "Building",   color: "#f78c6b" },
  value:    { label: "Value",      color: "#06d6a0" },
  address:  { label: "Address",    color: "#94a3b8" },
};
const MONEY_FIELDS = new Set(["Assessed value", "Last sale price"]);
const NUMBER_FIELDS = new Set(["Actual area (sq ft)", "Living area (sq ft)", "Lot size"]);

const DARK_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const SATELLITE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

const state = { dates: [], index: 0, cumulative: false, enabled: new Set(Object.keys(CATEGORIES)), timer: null };
const byFolio = new Map();
let runs = [];

const $ = (id) => document.getElementById(id);
const fmtDate = (d) => new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtValue(field, v) {
  if (v === "" || v == null) return "—";
  const n = Number(v);
  if (!Number.isNaN(n) && MONEY_FIELDS.has(field)) return "$" + n.toLocaleString();
  if (!Number.isNaN(n) && NUMBER_FIELDS.has(field)) return n.toLocaleString();
  return v;
}

function centroid(geom) {
  const ring = geom.type === "Polygon" ? geom.coordinates[0] : geom.coordinates[0][0];
  let x = 0, y = 0;
  for (const [cx, cy] of ring) { x += cx; y += cy; }
  return [x / ring.length, y / ring.length];
}

const map = new maplibregl.Map({
  container: "map",
  style: DARK_STYLE,
  center: [-80.43, 25.65],
  zoom: 9.3,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

async function loadJSON(url, fallback) {
  try {
    const r = await fetch(url, { cache: "no-cache" });
    return r.ok ? await r.json() : fallback;
  } catch { return fallback; }
}

map.on("load", async () => {
  const [runList, changes] = await Promise.all([
    loadJSON("data/runs.json", []),
    loadJSON("data/changes.geojson", { type: "FeatureCollection", features: [] }),
  ]);
  runs = runList;

  for (const f of changes.features) {
    const p = f.properties;
    if (!byFolio.has(p.folio)) byFolio.set(p.folio, []);
    byFolio.get(p.folio).push(p);
  }
  const points = {
    type: "FeatureCollection",
    features: changes.features.map((f) => ({ type: "Feature", properties: f.properties, geometry: { type: "Point", coordinates: centroid(f.geometry) } })),
  };
  state.dates = [...new Set(runs.filter((r) => !r.baseline).map((r) => r.date))].sort();

  const firstSymbol = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
  map.addSource("satellite", { type: "raster", tiles: [SATELLITE_TILES], tileSize: 256, maxzoom: 19,
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics" });
  map.addLayer({ id: "satellite", type: "raster", source: "satellite", layout: { visibility: "none" } }, firstSymbol);

  const color = ["match", ["get", "cat"], ...Object.entries(CATEGORIES).flatMap(([k, v]) => [k, v.color]), "#ffffff"];
  map.addSource("parcels", { type: "geojson", data: changes, attribution: "Parcels: Miami-Dade County" });
  map.addSource("points", { type: "geojson", data: points });
  map.addLayer({ id: "glow", type: "circle", source: "points", maxzoom: 14,
    paint: { "circle-color": color, "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 6, 13, 14], "circle-blur": 1, "circle-opacity": 0.35 } });
  map.addLayer({ id: "dots", type: "circle", source: "points", maxzoom: 14,
    paint: { "circle-color": color, "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 1.8, 13, 4.5], "circle-opacity": 0.95 } });
  map.addLayer({ id: "fill", type: "fill", source: "parcels", minzoom: 13,
    paint: { "fill-color": color, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 13, 0, 14, 0.45] } });
  map.addLayer({ id: "outline", type: "line", source: "parcels", minzoom: 13,
    paint: { "line-color": color, "line-width": 1.4 } });

  for (const id of ["dots", "fill"]) {
    map.on("click", id, (e) => showParcel(e.features[0].properties.folio));
    map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
  }

  buildLegend();
  buildSlider();
  update();
});

function buildLegend() {
  const el = $("legend");
  for (const [key, { label, color }] of Object.entries(CATEGORIES)) {
    const b = document.createElement("button");
    b.innerHTML = `<i style="background:${color}"></i>${label}`;
    b.onclick = () => {
      state.enabled.has(key) ? state.enabled.delete(key) : state.enabled.add(key);
      b.classList.toggle("off", !state.enabled.has(key));
      update();
    };
    el.appendChild(b);
  }
}

function buildSlider() {
  const s = $("slider");
  s.max = Math.max(0, state.dates.length - 1);
  state.index = s.max;
  s.value = state.index;
  s.oninput = () => { state.index = Number(s.value); update(); };
  $("cumulative").onchange = (e) => { state.cumulative = e.target.checked; update(); };
  const ticks = $("ticks");
  if (state.dates.length > 1 && state.dates.length <= 120) {
    state.dates.forEach((_, i) => {
      const t = document.createElement("span");
      t.style.left = (i / (state.dates.length - 1)) * 100 + "%";
      ticks.appendChild(t);
    });
  }
  $("play").onclick = togglePlay;
  $("play").disabled = state.dates.length < 2;
}

function togglePlay() {
  if (state.timer) { clearInterval(state.timer); state.timer = null; $("play").textContent = "▶"; return; }
  if (state.index >= state.dates.length - 1) state.index = 0;
  $("play").textContent = "❚❚";
  state.timer = setInterval(() => {
    $("slider").value = state.index;
    update();
    if (state.index >= state.dates.length - 1) togglePlay(); else state.index++;
  }, 1100);
}

function update() {
  const base = runs.find((r) => r.baseline);
  const latest = runs[runs.length - 1];
  if (!state.dates.length) {
    $("summary").textContent = base
      ? `First snapshot taken ${fmtDate(base.date)} (${base.parcels.toLocaleString()} parcels). Changes appear after the county's next update.`
      : "No snapshots yet.";
    $("date-label").textContent = "–";
    $("day-stats").textContent = "";
    for (const id of ["glow", "dots", "fill", "outline"]) map.setFilter(id, ["==", ["get", "date"], ""]);
    return;
  }
  const date = state.dates[state.index];
  $("summary").textContent = `Tracking ${latest.parcels.toLocaleString()} parcels since ${fmtDate((base || runs[0]).date)}. Click a parcel for its history.`;
  $("date-label").textContent = (state.cumulative ? "Up to " : "") + fmtDate(date);

  const dateFilter = state.cumulative ? ["<=", ["get", "date"], date] : ["==", ["get", "date"], date];
  const filter = ["all", dateFilter, ["in", ["get", "cat"], ["literal", [...state.enabled]]]];
  for (const id of ["glow", "dots", "fill", "outline"]) map.setFilter(id, filter);

  const dayRuns = runs.filter((r) => r.date === date);
  const changes = dayRuns.reduce((n, r) => n + r.changes, 0);
  const parcels = dayRuns.reduce((n, r) => n + r.parcels_changed, 0);
  const bulk = Object.assign({}, ...dayRuns.map((r) => r.bulk));
  let text = `${fmtDate(date)}: ${changes.toLocaleString()} field changes on ${parcels.toLocaleString()} parcels.`;
  const bulkNames = Object.keys(bulk);
  if (bulkNames.length) text += ` County-wide updates not drawn: ${bulkNames.join(", ")}.`;
  $("day-stats").textContent = text;
}

function showParcel(folio) {
  const entries = (byFolio.get(folio) || []).slice().sort((a, b) => b.date.localeCompare(a.date));
  if (!entries.length) return;
  const addr = entries.find((e) => e.addr)?.addr || "No site address";
  let html = `<h2>${esc(addr)}</h2><div class="folio">Folio ${esc(folio)}</div>`;
  for (const e of entries) {
    const rows = JSON.parse(e.ev).map(([field, oldV, newV]) =>
      `<tr><td class="f">${esc(field)}</td><td><span class="old">${esc(fmtValue(field, oldV))}</span> <span class="new">${esc(fmtValue(field, newV))}</span></td></tr>`
    ).join("");
    html += `<div class="entry" style="--dot:${CATEGORIES[e.cat]?.color || "#fff"}"><div class="when">${fmtDate(e.date)}</div><table>${rows}</table></div>`;
  }
  $("panel-body").innerHTML = html;
  $("panel").classList.remove("hidden");
}
$("panel-close").onclick = () => $("panel").classList.add("hidden");

document.querySelectorAll(".basemaps button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".basemaps button").forEach((x) => x.classList.toggle("on", x === b));
    map.setLayoutProperty("satellite", "visibility", b.dataset.base === "satellite" ? "visible" : "none");
  };
});
