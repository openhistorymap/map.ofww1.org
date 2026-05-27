// map.ofww1.org — day-snapshot atlas of the First World War.
//
// Loads `data/manifest.json`, then every year bucket + the memorials file in
// parallel into one in-memory FeatureCollection. Filtering is a single
// MapLibre filter expression on the points layer — much faster than re-setting
// source data on every slider tick.

const KIND_ORDER = ["attack", "battle", "memorial"];
const ATTACKER_ORDER = ["Allied", "Central Powers"];

// Hardcoded hex — NOT read from CSS custom properties. The design tokens are
// authored in OKLCH, and modern browsers serialise getComputedStyle().color of
// an oklch variable back as `oklch(...)`, which maplibre-gl 4.x cannot parse —
// feeding it into a paint property throws and the whole layer fails to add.
// These hex values track the --kind-* and attacker tokens in style.css.
const KIND_COLORS_LIGHT = { attack: "#2b211a", battle: "#2a3f6d", memorial: "#5a7a4b" };
const KIND_COLORS_DARK  = { attack: "#d4c2a8", battle: "#7da8d9", memorial: "#9bbf8f" };
// Central Powers stroke: ochre. Allied stroke: same as fill (no contrast).
const ATTACKER_STROKE_LIGHT = { Allied: null, "Central Powers": "#a8742a" };
const ATTACKER_STROKE_DARK  = { Allied: null, "Central Powers": "#d4a86a" };

const SOURCE_ID = "w1m-features";
const LAYER_ID = "w1m-points";
const SELECTED_LAYER_ID = "w1m-selected";

const MAP_STYLES = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
};

const EPOCH = new Date(Date.UTC(1914, 0, 1));
const ARMISTICE_DAY = Math.round((Date.UTC(1918, 10, 11) - EPOCH.getTime()) / 86400000); // 1775
const DAY_MIN_DEFAULT = (Date.UTC(1914, 6, 28) - EPOCH.getTime()) / 86400000;            // 208 — declaration of war
const DAY_MAX_DEFAULT = ARMISTICE_DAY + 30;                                              // small buffer past armistice

// Notable days the slider should "click onto" — captioned in the readout when
// the user lands on or near them. Kept short and famous; not exhaustive.
const NOTABLE_DAYS = [
  { day: dayFor(1914, 7, 28),  label: "Austria-Hungary declares war on Serbia" },
  { day: dayFor(1914, 8, 4),   label: "Britain enters the war" },
  { day: dayFor(1914, 9, 6),   label: "First Battle of the Marne begins" },
  { day: dayFor(1915, 4, 22),  label: "Second Battle of Ypres — first chlorine attack" },
  { day: dayFor(1915, 5, 7),   label: "Lusitania sunk" },
  { day: dayFor(1916, 2, 21),  label: "Battle of Verdun begins" },
  { day: dayFor(1916, 5, 31),  label: "Battle of Jutland" },
  { day: dayFor(1916, 7, 1),   label: "First day on the Somme" },
  { day: dayFor(1917, 4, 6),   label: "United States enters the war" },
  { day: dayFor(1917, 7, 31),  label: "Battle of Passchendaele begins" },
  { day: dayFor(1917, 10, 24), label: "Battle of Caporetto begins" },
  { day: dayFor(1918, 3, 21),  label: "Spring Offensive begins" },
  { day: dayFor(1918, 11, 11), label: "Armistice — silence at the eleventh hour" },
];

function dayFor(y, m, d) {
  return Math.round((Date.UTC(y, m - 1, d) - EPOCH.getTime()) / 86400000);
}

function dateForDay(day) {
  return new Date(EPOCH.getTime() + day * 86400000);
}

function formatDateLong(day) {
  const d = dateForDay(day);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

const state = {
  manifest: null,
  features: [],
  enabledKinds: new Set(KIND_ORDER),
  enabledAttackers: new Set(ATTACKER_ORDER),
  day: DAY_MIN_DEFAULT,
  dayMin: DAY_MIN_DEFAULT,
  dayMax: DAY_MAX_DEFAULT,
  snapshotMode: true,
  playing: false,
  playDaysPerSecond: 14,
  theme: document.documentElement.getAttribute("data-theme") || "light",
  selectedFeatureId: null,
  selectedFeature: null,
  suppressNextMoveUrlWrite: false,
};

const slider = document.getElementById("day-slider");
const playBtn = document.getElementById("play-btn");
const dayValueEl = document.getElementById("day-value");
const dayMetaLineEl = document.getElementById("day-meta-line");
const dayAllBtn = document.getElementById("day-all");

const map = new maplibregl.Map({
  container: "map",
  style: MAP_STYLES[state.theme],
  center: [10, 49],
  zoom: 3.6,
  maxZoom: 18,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

document.body.dataset.snapshot = "on";
document.body.dataset.playing = "false";

map.on("load", async () => {
  addLayers();
  await bootstrap();
});

// ── data loading ─────────────────────────────────────────────

async function bootstrap() {
  showLoadingVeil("opening the atlas…");
  let manifest;
  try {
    const r = await fetch("data/manifest.json", { cache: "no-cache" });
    manifest = await r.json();
  } catch (e) {
    showLoadingVeil("the atlas is still being typeset — try again soon.");
    return;
  }
  state.manifest = manifest;
  renderMeta();

  const buckets = manifest.buckets || [];
  const memorialFile = manifest.memorials && manifest.memorials.file
    ? manifest.memorials.file
    : "memorials.geojson";

  const fetches = buckets.map((b) =>
    fetch(`data/${b.file}`, { cache: "no-cache" })
      .then((r) => r.ok ? r.json() : { features: [] })
      .catch(() => ({ features: [] })),
  );
  fetches.push(
    fetch(`data/${memorialFile}`, { cache: "no-cache" })
      .then((r) => r.ok ? r.json() : { features: [] })
      .catch(() => ({ features: [] })),
  );
  const results = await Promise.all(fetches);
  const all = [];
  for (const fc of results) {
    if (fc && Array.isArray(fc.features)) {
      for (const f of fc.features) all.push(f);
    }
  }
  state.features = all;

  // Day range: armistice ±N days, clamped to data extent
  state.dayMin = DAY_MIN_DEFAULT;
  state.dayMax = DAY_MAX_DEFAULT;
  let maxFeatureDay = 0;
  for (const f of all) {
    const d = f.properties && f.properties.day_to;
    if (typeof d === "number" && d > maxFeatureDay) maxFeatureDay = d;
  }
  if (maxFeatureDay > state.dayMax) state.dayMax = maxFeatureDay;

  slider.min = String(state.dayMin);
  slider.max = String(state.dayMax);

  const url = readUrl();
  if (Array.isArray(url.kinds) && url.kinds.length) {
    state.enabledKinds = new Set(url.kinds.filter((k) => KIND_ORDER.includes(k)));
  }
  if (Array.isArray(url.attackers) && url.attackers.length) {
    state.enabledAttackers = new Set(url.attackers.filter((a) => ATTACKER_ORDER.includes(a)));
  }
  if (url.snap === false) {
    state.snapshotMode = false;
    document.body.dataset.snapshot = "off";
  }
  if (Number.isFinite(url.d)) {
    state.day = clamp(url.d, state.dayMin, state.dayMax);
  } else {
    state.day = pickDefaultDay();
  }
  slider.value = String(state.day);

  renderKindToggles();
  renderAttackerToggles();
  updateDayDisplay();
  setSliderTrack();
  applyFilter();
  setSourceData();
  hideLoadingVeil();

  if (url.lat != null && url.lon != null && url.z != null) {
    state.suppressNextMoveUrlWrite = true;
    map.jumpTo({ center: [url.lon, url.lat], zoom: url.z });
  }
  if (url.p) {
    const f = state.features.find((x) => x.id === url.p);
    if (f) selectFeature(f, { fromUrl: true });
  }
  writeUrl();
}

// ── map layers ───────────────────────────────────────────────

function addLayers() {
  map.addSource(SOURCE_ID, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });

  map.addLayer({
    id: LAYER_ID,
    type: "circle",
    source: SOURCE_ID,
    paint: {
      "circle-color": kindColorExpr(),
      "circle-radius": [
        "interpolate", ["linear"], ["zoom"],
        2, 2.2,
        4, 3.0,
        7, 4.0,
        11, 5.4,
        15, 7.0,
        18, 9.2,
      ],
      "circle-opacity": [
        "case",
        ["==", ["get", "kind"], "memorial"], 0.72,
        ["==", ["get", "kind"], "battle"], 0.82,
        0.78,
      ],
      "circle-stroke-color": attackerStrokeExpr(),
      "circle-stroke-width": [
        "case",
        ["==", ["get", "attacker"], "Central Powers"], 1.6,
        0.7,
      ],
    },
  });

  map.addLayer({
    id: SELECTED_LAYER_ID,
    type: "circle",
    source: SOURCE_ID,
    filter: ["==", ["id"], ""],
    paint: {
      "circle-color": "rgba(0,0,0,0)",
      "circle-radius": [
        "interpolate", ["linear"], ["zoom"],
        2, 7,
        7, 10,
        15, 16,
      ],
      "circle-stroke-color": kindColorExpr(),
      "circle-stroke-width": 2.2,
    },
  });

  map.on("click", LAYER_ID, (e) => {
    if (e.features && e.features[0]) selectFeature(e.features[0]);
  });
  map.on("mouseenter", LAYER_ID, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", LAYER_ID, () => (map.getCanvas().style.cursor = ""));
}

function setSourceData() {
  const src = map.getSource(SOURCE_ID);
  if (!src) return;
  src.setData({ type: "FeatureCollection", features: state.features });
}

function kindColorExpr() {
  const p = state.theme === "dark" ? KIND_COLORS_DARK : KIND_COLORS_LIGHT;
  return [
    "match", ["get", "kind"],
    "attack", p.attack,
    "battle", p.battle,
    "memorial", p.memorial,
    p.attack,
  ];
}

function attackerStrokeExpr() {
  const s = state.theme === "dark" ? ATTACKER_STROKE_DARK : ATTACKER_STROKE_LIGHT;
  const central = s["Central Powers"];
  const allied = state.theme === "dark" ? "rgba(20,16,12,0.65)" : "rgba(255,250,240,0.85)";
  return [
    "case",
    ["==", ["get", "attacker"], "Central Powers"], central,
    allied,
  ];
}

// ── filter expression ────────────────────────────────────────

function applyFilter() {
  const expr = buildFilter();
  if (!map.getLayer(LAYER_ID)) return;
  map.setFilter(LAYER_ID, expr);
  if (state.selectedFeatureId) {
    map.setFilter(SELECTED_LAYER_ID, ["==", ["id"], state.selectedFeatureId]);
  } else {
    map.setFilter(SELECTED_LAYER_ID, ["==", ["id"], ""]);
  }
}

function buildFilter() {
  const kindArr = Array.from(state.enabledKinds);
  if (!kindArr.length) return ["==", ["literal", "x"], "y"]; // matches nothing
  const kindClause = ["in", ["get", "kind"], ["literal", kindArr]];

  // Attacker filter applies to `kind == attack` only. Battles and memorials
  // are not partitioned by attacker — they always show regardless of which
  // attacker toggles are on.
  const attackerArr = Array.from(state.enabledAttackers);
  const attackerClause = [
    "any",
    ["!=", ["get", "kind"], "attack"],
    ["in", ["coalesce", ["get", "attacker"], "Allied"], ["literal", attackerArr.length ? attackerArr : ["__none__"]]],
  ];

  if (!state.snapshotMode) return ["all", kindClause, attackerClause];

  const D = state.day;
  // Time filter: memorials are timeless ("show always"); temporal features
  // appear when day ∈ [day_from, day_to] (closed interval).
  const dayClause = [
    "case",
    ["==", ["get", "kind"], "memorial"], true,
    [
      "all",
      ["<=", ["coalesce", ["get", "day_from"], 1e9], D],
      [">=", ["coalesce", ["get", "day_to"], -1e9], D],
    ],
  ];
  return ["all", kindClause, attackerClause, dayClause];
}

// ── day UI ───────────────────────────────────────────────────

function updateDayDisplay() {
  dayValueEl.textContent = formatDateLong(state.day);

  // Surface a notable-day caption when on or near a flagged day.
  let captionEntry = null;
  for (const entry of NOTABLE_DAYS) {
    if (Math.abs(entry.day - state.day) <= 1) {
      captionEntry = entry;
      break;
    }
  }
  if (captionEntry) {
    dayMetaLineEl.textContent = captionEntry.label;
    dayMetaLineEl.style.color = "var(--poppy)";
  } else {
    const daysIntoWar = state.day - DAY_MIN_DEFAULT;
    const sinceArm = state.day - ARMISTICE_DAY;
    if (daysIntoWar < 0) {
      dayMetaLineEl.textContent = `${Math.abs(daysIntoWar)} days before the declaration of war`;
    } else if (sinceArm > 0) {
      dayMetaLineEl.textContent = `${sinceArm} days after the armistice`;
    } else {
      dayMetaLineEl.textContent = `day ${daysIntoWar + 1} of the war`;
    }
    dayMetaLineEl.style.color = "";
  }
}

function setSliderTrack() {
  const min = parseFloat(slider.min);
  const max = parseFloat(slider.max);
  const v = parseFloat(slider.value);
  const pct = max > min ? ((v - min) / (max - min)) * 100 : 0;
  slider.style.setProperty("--slider-pct", `${pct.toFixed(2)}%`);
}

slider.addEventListener("input", (e) => {
  state.day = parseInt(e.target.value, 10);
  setSnapshotMode(true);
  updateDayDisplay();
  setSliderTrack();
  applyFilter();
  scheduleUrlWrite();
});

slider.addEventListener("change", () => writeUrl());

dayAllBtn.addEventListener("click", () => {
  setSnapshotMode(!state.snapshotMode);
  applyFilter();
  writeUrl();
});

function setSnapshotMode(on) {
  state.snapshotMode = !!on;
  document.body.dataset.snapshot = on ? "on" : "off";
  if (!on && state.playing) stopPlay();
}

// ── play loop ────────────────────────────────────────────────

let playTimer = null;
playBtn.addEventListener("click", () => {
  if (state.playing) stopPlay();
  else startPlay();
});

function startPlay() {
  setSnapshotMode(true);
  state.playing = true;
  document.body.dataset.playing = "true";
  const tickMs = Math.max(35, Math.round(1000 / state.playDaysPerSecond));
  playTimer = setInterval(() => {
    let next = state.day + 1;
    if (next > state.dayMax) next = state.dayMin;
    state.day = next;
    slider.value = String(next);
    updateDayDisplay();
    setSliderTrack();
    applyFilter();
  }, tickMs);
}

function stopPlay() {
  state.playing = false;
  document.body.dataset.playing = "false";
  if (playTimer) clearInterval(playTimer);
  playTimer = null;
  writeUrl();
}

// ── kind toggles ─────────────────────────────────────────────

function renderKindToggles() {
  const counts = { attack: 0, battle: 0, memorial: 0 };
  for (const f of state.features) {
    const k = f.properties && f.properties.kind;
    if (counts[k] != null) counts[k]++;
  }
  document.getElementById("kind-count-attack").textContent = counts.attack.toLocaleString();
  document.getElementById("kind-count-battle").textContent = counts.battle.toLocaleString();
  document.getElementById("kind-count-memorial").textContent = counts.memorial.toLocaleString();

  for (const row of document.querySelectorAll("#kind-list .kind-row")) {
    const k = row.dataset.kind;
    row.classList.toggle("off", !state.enabledKinds.has(k));
    row.onclick = () => {
      if (state.enabledKinds.has(k)) state.enabledKinds.delete(k);
      else state.enabledKinds.add(k);
      row.classList.toggle("off");
      applyFilter();
      writeUrl();
    };
  }

  document.getElementById("kind-all").onclick = () => {
    state.enabledKinds = new Set(KIND_ORDER);
    renderKindToggles();
    applyFilter();
    writeUrl();
  };
  document.getElementById("kind-none").onclick = () => {
    state.enabledKinds = new Set();
    renderKindToggles();
    applyFilter();
    writeUrl();
  };
}

function renderAttackerToggles() {
  const counts = { Allied: 0, "Central Powers": 0 };
  for (const f of state.features) {
    if (!f.properties || f.properties.kind !== "attack") continue;
    const a = f.properties.attacker || "Allied";
    if (counts[a] != null) counts[a]++;
  }
  document.getElementById("attacker-count-allied").textContent = counts.Allied.toLocaleString();
  document.getElementById("attacker-count-central").textContent = counts["Central Powers"].toLocaleString();
  for (const row of document.querySelectorAll("#attacker-list .kind-row")) {
    const a = row.dataset.attacker;
    row.classList.toggle("off", !state.enabledAttackers.has(a));
    row.onclick = () => {
      if (state.enabledAttackers.has(a)) state.enabledAttackers.delete(a);
      else state.enabledAttackers.add(a);
      row.classList.toggle("off");
      applyFilter();
      writeUrl();
    };
  }
}

// ── meta header ──────────────────────────────────────────────

function renderMeta() {
  const el = document.getElementById("meta-updated");
  const m = state.manifest;
  if (!m || !m.generated_at) {
    el.textContent = "the atlas is being typeset…";
    return;
  }
  const d = new Date(m.generated_at);
  const fmt = d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  const t = m.totals || {};
  const a = (t.attacks || 0).toLocaleString();
  const b = (t.battles || 0).toLocaleString();
  const mn = (t.memorials || 0).toLocaleString();
  el.innerHTML = `last gathered <strong style="font-style:normal;color:var(--ink-soft)">${fmt}</strong> · ${a} raids · ${b} battles · ${mn} memorials`;
}

// ── theme toggle ─────────────────────────────────────────────

document.getElementById("theme-toggle").addEventListener("click", () => {
  setTheme(state.theme === "light" ? "dark" : "light");
});

function setTheme(theme) {
  state.theme = theme;
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("w1m-theme", theme); } catch (e) {}
  const cam = { center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() };
  map.setStyle(MAP_STYLES[theme]);
  map.once("style.load", () => {
    map.jumpTo(cam);
    addLayers();
    setSourceData();
    applyFilter();
  });
}

// ── selection / detail panel ─────────────────────────────────

function selectFeature(feature, { fromUrl = false } = {}) {
  state.selectedFeatureId = feature.id;
  state.selectedFeature = feature;
  if (map.getLayer(SELECTED_LAYER_ID)) {
    map.setFilter(SELECTED_LAYER_ID, ["==", ["id"], feature.id]);
  }
  openDetail(feature, { fromUrl });
}

const KIND_LABELS = {
  attack: "air raid",
  battle: "battle",
  memorial: "memorial",
};

function openDetail(feature, { fromUrl = false } = {}) {
  const detail = document.getElementById("detail");
  const body = document.getElementById("detail-body");
  const p = feature.properties || {};
  if (!fromUrl) writeUrl({ push: true });

  const kind = p.kind || "attack";
  const kindLabel = KIND_LABELS[kind] || kind;
  const kindGlyph = kindGlyphSvg(kind);

  const title = p.name || (kind === "memorial" ? "war memorial" : "(unnamed)");
  const place = buildPlaceLine(p, kind);
  const dateLine = buildDateLine(p, kind);
  const attackerPill = (kind === "attack" && p.attacker)
    ? `<span class="attacker-pill" data-attacker="${escapeAttr(p.attacker)}">${escapeHtml(p.attacker)}</span>`
    : "";
  const bda = (kind === "attack" && p.bda) ? `<div class="bda-quote">“${escapeHtml(p.bda)}”</div>` : "";
  const image = p.image ? `<img class="detail-image" src="${escapeAttr(p.image)}" loading="lazy" alt="${escapeAttr(title)}" onerror="this.remove()" />` : "";
  const links = buildLinks(p);
  const attribution = buildAttribution(p);

  body.innerHTML = `
    <span class="detail-kind" data-kind="${kind}">
      <span class="kind-glyph">${kindGlyph}</span>
      ${escapeHtml(kindLabel)}
      ${attackerPill}
    </span>
    <h2 class="detail-title">${escapeHtml(title)}</h2>
    <div class="detail-sub">${place}</div>
    ${dateLine ? `<div class="dateline">${dateLine}</div>` : ""}
    ${image}
    ${bda}
    <div id="wd-slot"></div>
    <div class="detail-section">
      <h4>About this point</h4>
      <dl class="tag-grid">${renderTagRows(p, kind)}</dl>
    </div>
    ${links.length ? `<div class="detail-section"><h4>Elsewhere</h4><div class="detail-links">${links.join("")}</div></div>` : ""}
    <p class="attribution-note">${attribution}</p>
  `;
  detail.classList.add("open");
  detail.setAttribute("aria-hidden", "false");

  if (p.qid && /^Q\d+$/.test(p.qid)) {
    renderWdSlot(document.getElementById("wd-slot"), p.qid);
  }
}

function buildPlaceLine(p, kind) {
  if (kind === "attack") {
    const target = p.tgt_location || p.name || "—";
    const country = p.tgt_country ? `, ${p.tgt_country}` : "";
    return escapeHtml(target + country);
  }
  if (kind === "memorial") {
    return escapeHtml(p.country ? p.country : "");
  }
  // battle
  if (p.participants && p.participants.length) {
    return escapeHtml(`Participants: ${p.participants.join(", ")}`);
  }
  return "";
}

function buildDateLine(p, kind) {
  if (kind === "memorial") {
    return p.inception ? `<span>unveiled ${escapeHtml(String(p.inception))}</span>` : "";
  }
  const from = p.day_from, to = p.day_to;
  if (from == null && to == null) return "";
  if (from != null && to != null && from === to) {
    return `<span>${escapeHtml(formatDateLong(from))}</span>`;
  }
  const fs = from != null ? formatDateLong(from) : "?";
  const ts = to != null ? formatDateLong(to) : "?";
  return `<span>${escapeHtml(fs)}</span><span class="dash">→</span><span>${escapeHtml(ts)}</span>`;
}

function kindGlyphSvg(kind) {
  if (kind === "attack") {
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 L12 13 M8 9 L12 13 L16 9" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="18.5" r="3.2" fill="currentColor"/></svg>`;
  }
  if (kind === "battle") {
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4 L20 20 M20 4 L4 20" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" fill="none"/><circle cx="12" cy="12" r="2.4" fill="currentColor"/></svg>`;
  }
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="currentColor"/><circle cx="12" cy="12" r="2" fill="#1a1410"/></svg>`;
}

function buildLinks(p) {
  const out = [];
  if (p.qid && /^Q\d+$/.test(p.qid)) {
    out.push(`<a href="https://www.wikidata.org/wiki/${encodeURIComponent(p.qid)}" target="_blank" rel="noopener">Wikidata</a>`);
  }
  if (p.wikipedia) {
    if (/^https?:\/\//.test(p.wikipedia)) {
      out.push(`<a href="${escapeAttr(p.wikipedia)}" target="_blank" rel="noopener">Wikipedia</a>`);
    } else {
      const idx = p.wikipedia.indexOf(":");
      if (idx > 0) {
        const lang = p.wikipedia.slice(0, idx);
        const title = p.wikipedia.slice(idx + 1);
        out.push(`<a href="https://${lang}.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}" target="_blank" rel="noopener">Wikipedia</a>`);
      }
    }
  }
  if (p.src === "osm_memorials" && p.osm_type && p.osm_id) {
    out.push(`<a href="https://www.openstreetmap.org/${p.osm_type}/${p.osm_id}" target="_blank" rel="noopener">OpenStreetMap</a>`);
  }
  if (p.src === "thor" && p.ref) {
    out.push(`<a href="https://data.world/datamil/world-war-i-thor-data" target="_blank" rel="noopener">THOR record · ${escapeHtml(p.ref)}</a>`);
  }
  return out;
}

function buildAttribution(p) {
  if (p.src === "thor") return "Source: THOR Project · US Department of Defense (declassified 2016).";
  if (p.src === "wd_battles") return "Source: Wikidata · battle records, CC0.";
  if (p.src === "wd_german_raids") return "Source: Wikidata · German aerial bombardment records, CC0.";
  if (p.src === "wd_memorials") return "Source: Wikidata · war memorial records, CC0.";
  if (p.src === "osm_memorials") return "Source: OpenStreetMap contributors · ODbL.";
  return "";
}

const TAG_DISPLAY = {
  attack: {
    service: "service",
    unit: "unit",
    aircraft: "aircraft",
    planes: "planes attacking",
    departure: "departure",
    takeoff_time: "takeoff time",
    takeoff_base: "from base",
    weapon_type: "weapon type",
    weapon_weight_lb: "ordnance (lb)",
    bombload_lb: "bombload per a/c (lb)",
    altitude_ft: "altitude (ft)",
    tgt_type: "target type",
    weather: "weather",
    enemy_action: "enemy action",
    friendly_casualties: "friendly casualties",
    friendly_casualties_note: "casualties note",
    operation: "operation",
  },
  battle: {
    participants: "participants",
    attacker_side: "leading side",
    start_date: "started",
    end_date: "ended",
  },
  memorial: {
    commemorates: "commemorates",
    country: "country",
    inception: "unveiled",
    memorial_type: "type",
  },
};

function renderTagRows(p, kind) {
  const fields = TAG_DISPLAY[kind] || {};
  const rows = [];
  for (const [k, label] of Object.entries(fields)) {
    if (p[k] == null || p[k] === "") continue;
    let v = p[k];
    if (Array.isArray(v)) v = v.join(", ");
    rows.push(`<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(v))}</dd>`);
  }
  if (!rows.length) return `<dt>—</dt><dd>no extra notes recorded</dd>`;
  return rows.join("");
}

// ── Wikidata enrichment (on-demand) ─────────────────────────

const wikidataCache = new Map();

function renderWdSlot(slot, qid) {
  if (!slot) return;
  slot.innerHTML = `
    <div class="detail-section">
      <h4>From Wikidata · ${escapeHtml(qid)}</h4>
      <div class="skeleton lg"></div>
      <div class="skeleton"></div>
      <div class="skeleton" style="width:60%"></div>
    </div>
  `;
  fetchWikidata(qid).then((data) => {
    if (!data) { slot.innerHTML = ""; return; }
    slot.innerHTML = `
      <div class="detail-section">
        <h4>From Wikidata · <a href="https://www.wikidata.org/wiki/${encodeURIComponent(qid)}" target="_blank" rel="noopener">${escapeHtml(qid)}</a></h4>
        ${data.image ? `<img class="detail-image" src="${escapeAttr(data.image)}" alt="${escapeAttr(data.label || "")}" loading="lazy" />` : ""}
        ${data.label ? `<p style="font-family:var(--font-display);font-size:20px;line-height:1.25;color:var(--ink);margin-bottom:8px;">${escapeHtml(data.label)}</p>` : ""}
        ${data.desc ? `<p style="color:var(--ink-soft);">${escapeHtml(data.desc)}</p>` : ""}
        ${data.wikipediaUrl ? `<p style="margin-top:8px;"><a href="${escapeAttr(data.wikipediaUrl)}" target="_blank" rel="noopener">Read more on Wikipedia →</a></p>` : ""}
      </div>
    `;
  });
}

async function fetchWikidata(qid) {
  if (wikidataCache.has(qid)) return wikidataCache.get(qid);
  const url = `https://www.wikidata.org/w/api.php?action=wbgetentities&ids=${encodeURIComponent(qid)}&props=labels%7Cdescriptions%7Cclaims%7Csitelinks%2Furls&languages=en&format=json&origin=*`;
  try {
    const r = await fetch(url);
    const j = await r.json();
    const ent = j.entities?.[qid];
    if (!ent) { wikidataCache.set(qid, null); return null; }
    const label = ent.labels?.en?.value;
    const desc = ent.descriptions?.en?.value;
    const imageFile = ent.claims?.P18?.[0]?.mainsnak?.datavalue?.value;
    const wikipediaUrl = ent.sitelinks?.enwiki?.url || null;
    const image = imageFile
      ? `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(imageFile)}?width=720`
      : null;
    const out = { label, desc, image, wikipediaUrl };
    wikidataCache.set(qid, out);
    return out;
  } catch (e) {
    wikidataCache.set(qid, null);
    return null;
  }
}

// ── URL hash sync ────────────────────────────────────────────

function readUrl() {
  let h = (location.hash || "").replace(/^#/, "");
  if (!h) return {};
  const params = new URLSearchParams(h);
  const out = {};
  const d = parseInt(params.get("d") || "", 10); if (Number.isFinite(d)) out.d = d;
  const lat = parseFloat(params.get("lat")); if (Number.isFinite(lat)) out.lat = lat;
  const lon = parseFloat(params.get("lon")); if (Number.isFinite(lon)) out.lon = lon;
  const z = parseFloat(params.get("z")); if (Number.isFinite(z)) out.z = z;
  const p = params.get("p"); if (p) out.p = p;
  const k = params.get("k"); if (k) out.kinds = k.split(",").filter(Boolean);
  const a = params.get("a"); if (a) out.attackers = a.split(",").filter(Boolean);
  const snap = params.get("snap"); if (snap === "off") out.snap = false;
  return out;
}

let urlWriteTimer = null;
function scheduleUrlWrite() {
  if (urlWriteTimer) clearTimeout(urlWriteTimer);
  urlWriteTimer = setTimeout(() => { writeUrl(); urlWriteTimer = null; }, 200);
}

function writeUrl({ push = false } = {}) {
  const params = new URLSearchParams();
  if (state.snapshotMode) params.set("d", String(state.day));
  else params.set("snap", "off");
  const kinds = Array.from(state.enabledKinds);
  if (kinds.length !== KIND_ORDER.length) params.set("k", kinds.join(","));
  const attackers = Array.from(state.enabledAttackers);
  if (attackers.length !== ATTACKER_ORDER.length) params.set("a", attackers.join(","));
  if (map && typeof map.getCenter === "function") {
    try {
      const c = map.getCenter();
      params.set("lat", c.lat.toFixed(4));
      params.set("lon", c.lng.toFixed(4));
      params.set("z", map.getZoom().toFixed(2));
    } catch (e) {}
  }
  if (state.selectedFeatureId) params.set("p", state.selectedFeatureId);
  const target = "#" + params.toString();
  if (target === location.hash) return;
  if (push) history.pushState(null, "", target);
  else history.replaceState(null, "", target);
}

map.on("moveend", () => {
  if (state.suppressNextMoveUrlWrite) {
    state.suppressNextMoveUrlWrite = false;
    return;
  }
  scheduleUrlWrite();
});

window.addEventListener("popstate", () => {
  const url = readUrl();
  if (Number.isFinite(url.d)) {
    state.day = url.d;
    slider.value = String(url.d);
    setSnapshotMode(true);
    updateDayDisplay();
    setSliderTrack();
  }
  if (url.snap === false) setSnapshotMode(false);
  if (Array.isArray(url.kinds)) {
    state.enabledKinds = new Set(url.kinds.filter((k) => KIND_ORDER.includes(k)));
    renderKindToggles();
  }
  if (Array.isArray(url.attackers)) {
    state.enabledAttackers = new Set(url.attackers.filter((a) => ATTACKER_ORDER.includes(a)));
    renderAttackerToggles();
  }
  if (url.lat != null && url.lon != null && url.z != null) {
    state.suppressNextMoveUrlWrite = true;
    map.jumpTo({ center: [url.lon, url.lat], zoom: url.z });
  }
  applyFilter();
  if (url.p) {
    const f = state.features.find((x) => x.id === url.p);
    if (f && f.id !== state.selectedFeatureId) selectFeature(f, { fromUrl: true });
  } else if (state.selectedFeatureId) {
    closeDetailUI();
  }
});

document.getElementById("detail-close").addEventListener("click", () => {
  closeDetailUI();
  if (state.selectedFeatureId) {
    state.selectedFeatureId = null;
    state.selectedFeature = null;
    if (map.getLayer(SELECTED_LAYER_ID)) {
      map.setFilter(SELECTED_LAYER_ID, ["==", ["id"], ""]);
    }
    writeUrl();
  }
});

function closeDetailUI() {
  const d = document.getElementById("detail");
  d.classList.remove("open");
  d.setAttribute("aria-hidden", "true");
}

// ── utilities ────────────────────────────────────────────────

function clamp(n, lo, hi) {
  if (n < lo) return lo;
  if (n > hi) return hi;
  return n;
}

// Land the slider on the first day a non-trivial number of attacks appear,
// rather than the bare edge of the data range. THOR's earliest mission is
// 1917-10-16 so without this the slider opens on a blank map.
function pickDefaultDay() {
  // Find the median day_from across attack features; if none, fall back to
  // the war's declaration day.
  const days = [];
  for (const f of state.features) {
    if (f.properties && f.properties.kind === "attack" && typeof f.properties.day_from === "number") {
      days.push(f.properties.day_from);
    }
  }
  if (!days.length) return clamp(DAY_MIN_DEFAULT, state.dayMin, state.dayMax);
  days.sort((a, b) => a - b);
  return clamp(days[Math.floor(days.length / 2)], state.dayMin, state.dayMax);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}
function escapeAttr(s) { return escapeHtml(s); }

// ── loading veil ─────────────────────────────────────────────

function showLoadingVeil(msg) {
  let veil = document.querySelector(".loading-veil");
  if (!veil) {
    veil = document.createElement("div");
    veil.className = "loading-veil";
    document.getElementById("map").appendChild(veil);
  }
  veil.textContent = msg;
  veil.classList.remove("gone");
}

function hideLoadingVeil() {
  const veil = document.querySelector(".loading-veil");
  if (!veil) return;
  veil.classList.add("gone");
  setTimeout(() => veil.remove(), 400);
}
