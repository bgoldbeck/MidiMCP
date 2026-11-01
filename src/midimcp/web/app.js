// MidiMCP web UI (beginner mode): library, transport, overview, tracks, checks, exports.
// All text from songs is inserted with textContent / DOM nodes, never as HTML.
import { Api, ApiError, getToken, setToken } from "./api.js";
import { Player, SPEEDS, formatTime } from "./player.js";

const $ = (id) => document.getElementById(id);
const COLORS = ["#d9a441", "#8fbf6a", "#6aa6d9", "#d97a6a", "#b48ad9", "#6ad9c4", "#d9d06a", "#d96ab0"];
const SVG_NS = "http://www.w3.org/2000/svg";

const state = {
  api: null,
  player: null,
  projects: [],
  view: null,
  instruments: [],
  pendingUpdate: null,
  socket: null,
  ownRevisions: new Set(), // revisions this page created; their events are not "news"
};

// ------------------------------------------------------------------ helpers

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else node.setAttribute(key, String(value));
  }
  return node;
}

const FRIENDLY = {
  INSTRUMENT_NOT_ALLOWED: "That instrument is not on this song's allowed list.",
  PERCUSSION_FORBIDDEN: "This song does not allow percussion.",
  LOCKED: "That part of the song is locked. Unlock it first.",
  REVISION_CONFLICT: "The song changed meanwhile. The latest version has been loaded; please try again.",
  RENDER_BLOCKED: "The song cannot be rendered right now.",
};

function describeError(error) {
  if (!(error instanceof ApiError)) return String(error?.message || error);
  const codes = (error.body?.validation?.errors || []).map((i) => i.code);
  const key = codes.find((c) => FRIENDLY[c]) || error.code;
  const detail = (error.body?.validation?.errors || []).map((i) => i.message).join("; ") || error.message;
  return FRIENDLY[key] ? `${FRIENDLY[key]} (${detail})` : `${error.code}: ${detail}`;
}

let toastTimer = null;
function showError(error) {
  const toast = $("toast");
  clearTimeout(toastTimer);
  if (!error) { toast.hidden = true; return; }
  $("toast-text").textContent = describeError(error);
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 12000);
}

function relativeTime(iso) {
  const seconds = (Date.now() - Date.parse(iso)) / 1000;
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

// --------------------------------------------------------------- connection

async function connect(token) {
  const candidate = new Api({ token });
  try {
    const status = await candidate.status();
    state.api = candidate;
    setToken(token);
    return status;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

function openEvents() {
  const pill = $("connection");
  const socket = state.api.events(onServerEvent);
  state.socket = socket;
  socket.onopen = () => { pill.textContent = "live"; pill.className = "pill ok"; };
  socket.onclose = () => {
    pill.textContent = "reconnecting…";
    pill.className = "pill busy";
    setTimeout(() => { if (state.socket === socket) openEvents(); }, 3000);
  };
}

function onServerEvent(event) {
  if (event.type === "project.deleted") {
    refreshLibrary().catch(() => {});
    if (state.view?.projectId === event.projectId) closeSong("This song was deleted (it is in the trash folder on the NAS).");
    return;
  }
  if (event.type !== "project.updated") return;
  refreshLibrary().catch(() => {});
  const view = state.view;
  if (!view || event.projectId !== view.projectId || event.revision <= view.revision) return;
  if (state.ownRevisions.has(`${event.projectId}@${event.revision}`)) return; // our own save
  const who = event.author === "agent" ? "an AI agent" : event.author;
  state.pendingUpdate = event;
  if (state.player.state === "playing") {
    $("update-text").textContent = `Revision ${event.revision} by ${who}: ${event.summary}`;
    $("update-banner").hidden = false;
  } else {
    openProject(view.projectId, { notice: `Updated to revision ${event.revision} by ${who}: ${event.summary}` });
  }
}

// ------------------------------------------------------------------ library

async function refreshLibrary() {
  const search = $("search").value.trim();
  const { projects } = await state.api.projects(search);
  state.projects = projects;
  const list = $("project-list");
  list.replaceChildren(...projects.map((p) => el("li", {
    class: state.view?.projectId === p.projectId ? "active" : "",
    "data-project": p.projectId,
    onclick: () => openProject(p.projectId).catch(showError),
  },
  el("span", { class: "title", text: p.title }),
  el("span", { class: "sub", text: [p.usage, `rev ${p.headRevision}`, relativeTime(p.updatedAt)].filter(Boolean).join(" · ") }))));
  $("library-empty").hidden = projects.length > 0 || Boolean(search);
}

// ------------------------------------------------------------------ project

async function openProject(projectId, { notice = "" } = {}) {
  showError(null);
  const keepTick = state.view?.projectId === projectId ? state.player.tick : 0;
  const view = await state.api.project(projectId);
  state.view = view;
  state.pendingUpdate = null;
  $("update-banner").hidden = true;
  $("welcome").hidden = true;
  $("welcome-note").hidden = true;
  $("song").hidden = false;
  renderHeader(view, notice);
  renderOverview(view);
  renderTracks(view);
  renderChecks(view);
  refreshExports().catch(() => {});
  for (const item of $("project-list").children) {
    item.classList.toggle("active", item.dataset.project === projectId);
  }
  await state.player.load(view, { speed: Number($("speed").value), keepTick }).catch(() => {});
}

function renderHeader(view, notice) {
  const t = view.timing;
  const key = view.score.tonality;
  const mode = key.mode === "ionian" ? "major" : key.mode === "aeolian" ? "minor" : key.mode;
  $("song-title").textContent = view.score.metadata.title;
  const template = view.brief.templateId ? ` · template: ${view.brief.templateId}` : "";
  $("song-meta").textContent = `${t.quarterNoteBpm} BPM · ${t.meter} · ${key.displaySpelling} ${mode} · ${t.bars} bars · ${formatTime(t.durationSeconds)}${template}`;
  const change = view.lastChange;
  $("last-change").textContent = notice || `Last change (${change.author}, ${relativeTime(change.createdAt)}): ${change.summary}`;
  $("revision").textContent = `revision ${view.revision}`;
}

const OVERVIEW = { width: 1000, gutter: 120, laneHeight: 46, top: 18, ruler: 18 };

function renderOverview(view) {
  const box = $("overview");
  const { totalTicks, ticksPerBar } = view.timing;
  const tracks = view.score.tracks;
  const { width, gutter, laneHeight, top, ruler } = OVERVIEW;
  const lanesBottom = top + Math.max(1, tracks.length) * laneHeight;
  const height = lanesBottom + ruler;
  const plot = width - gutter;
  const x = (tick) => gutter + (tick / totalTicks) * plot;
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Song overview" });

  // Section bands + labels in the top row (notes area only).
  for (const section of view.score.sections) {
    root.append(svg("rect", { class: "section", x: x(section.startTick), y: 0, width: x(section.endTick) - x(section.startTick), height: lanesBottom }));
    root.append(svg("text", { class: "section-label", x: x(section.startTick) + 4, y: 12, text: section.label }));
  }
  // Bar lines through the lanes; numbers in their own ruler row underneath.
  const bars = Math.ceil(totalTicks / ticksPerBar);
  const labelEvery = bars > 48 ? 8 : bars > 24 ? 4 : bars > 12 ? 2 : 1;
  root.append(svg("rect", { class: "ruler", x: gutter, y: lanesBottom, width: plot, height: ruler }));
  for (let bar = 0; bar <= bars; bar++) {
    const bx = x(bar * ticksPerBar);
    root.append(svg("line", { class: "bar-line", x1: bx, x2: bx, y1: top, y2: lanesBottom + (bar % labelEvery === 0 ? 5 : 0) }));
    if (bar < bars && bar % labelEvery === 0) {
      root.append(svg("text", { class: "bar-label", x: bx + 3, y: height - 4, text: bar + 1 }));
    }
  }
  root.append(svg("text", { class: "ruler-title", x: gutter - 8, y: height - 4, "text-anchor": "end", text: "bar" }));
  tracks.forEach((track, index) => {
    const y0 = top + index * laneHeight;
    root.append(svg("rect", { class: "lane", x: gutter, y: y0 + 2, width: plot, height: laneHeight - 4 }));
    // Track name lives in the left gutter, never on top of notes.
    const label = track.name.length > 16 ? `${track.name.slice(0, 15)}…` : track.name;
    root.append(svg("rect", { class: `lane-swatch c${index % COLORS.length}`, x: 4, y: y0 + laneHeight / 2 - 5, width: 8, height: 10, rx: 2 }));
    const name = svg("text", { class: "lane-label", x: 18, y: y0 + laneHeight / 2 + 4, text: label });
    name.append(svg("title", { text: track.name }));
    root.append(name);
    const pitches = track.notes.map((n) => n.pitch);
    const low = Math.min(...pitches, 127);
    const high = Math.max(...pitches, 0);
    const span = Math.max(1, high - low);
    for (const note of track.notes) {
      const ny = y0 + 5 + (1 - (note.pitch - low) / span) * (laneHeight - 16);
      root.append(svg("rect", {
        class: "note", x: x(note.startTick), y: ny, rx: 1,
        width: Math.max(1.5, (note.durationTicks / totalTicks) * plot), height: 6,
        fill: track.mute ? "#5a5047" : COLORS[index % COLORS.length],
      }));
    }
  });
  const loop = view.score.timeline.loop;
  if (loop.enabled) {
    root.append(svg("rect", { class: "loop", x: x(loop.startTick) + 1, y: top, width: x(loop.endTick) - x(loop.startTick) - 2, height: lanesBottom - top - 1 }));
  }
  const playhead = svg("line", { class: "playhead", x1: gutter, x2: gutter, y1: 0, y2: lanesBottom, id: "playhead" });
  root.append(playhead);
  root.addEventListener("click", (event) => {
    const rect = root.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * width;
    if (svgX < gutter) return;
    state.player.seekTick(Math.round(((svgX - gutter) / plot) * totalTicks));
  });
  box.replaceChildren(root);
}

function movePlayhead(tick) {
  const line = document.getElementById("playhead");
  if (!line || !state.view) return;
  const px = OVERVIEW.gutter + (tick / state.view.timing.totalTicks) * (OVERVIEW.width - OVERVIEW.gutter);
  line.setAttribute("x1", px);
  line.setAttribute("x2", px);
}

function lockedTracks(view) {
  const locks = new Map();
  for (const lock of view.brief.locks) {
    const label = lock.startTick == null ? "locked" : "partly locked";
    if (!locks.has(lock.trackId) || label === "locked") locks.set(lock.trackId, label);
  }
  return locks;
}

function renderTracks(view) {
  const locks = lockedTracks(view);
  const rows = view.score.tracks.map((track, index) => {
    const wholeLock = locks.get(track.id) === "locked";
    const allowed = view.brief.allowedInstrumentIds; // null = any instrument
    const instrumentSelect = el("select", {
      disabled: wholeLock || track.isPercussion,
      "aria-label": `Instrument for ${track.name}`,
      onchange: (e) => changeInstrument(track, e.target.value, allowed),
    });
    instrumentSelect.append(...instrumentOptions(track, allowed));
    const db = el("span", { class: "db", text: `${track.gainDb} dB` });
    const volume = el("input", {
      type: "range", min: -30, max: 6, step: 1, value: track.gainDb, disabled: wholeLock,
      "aria-label": `Volume for ${track.name}`,
      oninput: (e) => { db.textContent = `${e.target.value} dB`; },
      onchange: (e) => saveTrack(track.id, { gainDb: Number(e.target.value) }),
    });
    const mute = el("input", {
      type: "checkbox", checked: track.mute, disabled: wholeLock,
      "aria-label": `Mute ${track.name}`,
      onchange: (e) => saveTrack(track.id, { mute: e.target.checked }),
    });
    return el("tr", { "data-track": track.id },
      el("td", {},
        el("span", { class: `swatch c${index % COLORS.length}` }),
        track.name,
        track.role ? el("span", { class: "role", text: track.role }) : null,
        locks.has(track.id) ? el("span", { class: "lock", text: `🔒 ${locks.get(track.id)}` }) : null),
      el("td", {}, instrumentSelect, resetButton(track, "instrument", wholeLock)),
      el("td", {}, volume, db, resetButton(track, "volume", wholeLock)),
      el("td", {}, mute),
      el("td", { text: track.notes.length }),
      el("td", {}, resetButton(track, "all", wholeLock)));
  });
  if (!rows.length) rows.push(el("tr", {}, el("td", { colspan: 6, class: "hint", text: "No tracks yet." })));
  $("track-rows").replaceChildren(...rows);
  const allowed = view.brief.allowedInstrumentIds;
  const names = (allowed || []).map((id) => state.instruments.find((i) => i.id === id)?.name || id);
  $("allowed-instruments").textContent = allowed ? `Allowed instruments for this song: ${names.join(", ")}` : "";
  $("allowed-instruments").hidden = !allowed;
}

const FAMILY_LABELS = [
  ["wind", "Woodwinds"],
  ["brass", "Brass"],
  ["plucked", "Plucked strings"],
  ["strings", "Bowed strings"],
  ["keyboard", "Keyboards & organs"],
  ["mallet", "Bells & mallets"],
  ["voice", "Voices"],
  ["pad", "Pads"],
  ["bass", "Bass"],
  ["percussion-melodic", "Timpani"],
  ["drums", "Drums"],
  ["gm", "Other General MIDI"],
];

/** Alphabetical options grouped by instrument family; the song's allowed list comes first. */
function instrumentOptions(track, allowed) {
  const byName = (a, b) => a.name.localeCompare(b.name);
  const pool = state.instruments.filter((i) => i.isPercussion === track.isPercussion);
  if (!pool.some((i) => i.id === track.instrumentId)) {
    pool.push({ id: track.instrumentId, name: track.instrumentId, family: "gm" });
  }
  const option = (i, note = "") => el("option", { value: i.id, selected: i.id === track.instrumentId, text: i.name + note });
  const groups = [];
  let rest = pool;
  if (allowed) {
    const inSong = pool.filter((i) => allowed.includes(i.id) || i.id === track.instrumentId).sort(byName);
    groups.push(el("optgroup", { label: "In this song" }, inSong.map((i) => option(i))));
    rest = pool.filter((i) => !inSong.includes(i));
  }
  for (const [family, label] of FAMILY_LABELS) {
    const members = rest.filter((i) => (i.family || "gm") === family).sort(byName);
    if (members.length) {
      groups.push(el("optgroup", { label: allowed ? `${label} (adds to song)` : label }, members.map((i) => option(i))));
    }
  }
  const known = new Set(FAMILY_LABELS.map(([f]) => f));
  const leftovers = rest.filter((i) => !known.has(i.family || "gm")).sort(byName);
  if (leftovers.length) groups.push(el("optgroup", { label: "Other" }, leftovers.map((i) => option(i))));
  return groups;
}

function instrumentName(id) {
  return state.instruments.find((i) => i.id === id)?.name || id;
}

/** Which settings differ from the track's default (its first revision / template choice). */
function changedFields(track) {
  const d = state.view?.trackDefaults?.[track.id];
  if (!d) return [];
  const fields = [];
  if (d.instrumentId !== track.instrumentId) fields.push("instrument");
  if (d.gainDb !== track.gainDb) fields.push("volume");
  if (d.pan !== track.pan) fields.push("pan");
  if (d.mute !== track.mute) fields.push("mute");
  return fields;
}

function resetButton(track, what, locked) {
  const d = state.view?.trackDefaults?.[track.id];
  const changed = changedFields(track);
  const fields = what === "all" ? changed : changed.filter((f) => f === what);
  if (!d || !fields.length || locked) return what === "all" ? el("span", { class: "hint", text: "default" }) : null;
  const parts = {
    instrument: `instrument → ${instrumentName(d.instrumentId)}`,
    volume: `volume → ${d.gainDb} dB`,
    pan: `pan → ${d.pan}`,
    mute: d.mute ? "muted" : "unmuted",
  };
  const label = what === "all" ? "Reset" : "↺";
  return el("button", {
    class: what === "all" ? "secondary small" : "icon-button",
    title: `Back to default (revision ${d.revision}): ${fields.map((f) => parts[f]).join(", ")}`,
    "aria-label": `Reset ${what === "all" ? "track" : what} of ${track.name} to default`,
    "data-reset": what,
    onclick: () => resetTrack(track.id, fields),
  }, label);
}

async function resetTrack(trackId, fields) {
  const view = state.view;
  try {
    const result = await state.api.resetTrack(view.projectId, trackId, { expectedRevision: view.revision, fields });
    state.ownRevisions.add(`${view.projectId}@${result.revision}`);
    await openProject(view.projectId);
  } catch (error) {
    if (error instanceof ApiError && error.code === "REVISION_CONFLICT") {
      await openProject(view.projectId, { notice: "The song changed meanwhile; reloaded the latest version. Please try again." });
    } else {
      showError(error);
    }
  }
}

function changeInstrument(track, instrumentId, allowed) {
  if (allowed && !allowed.includes(instrumentId)) {
    const name = state.instruments.find((i) => i.id === instrumentId)?.name || instrumentId;
    const ok = window.confirm(`This song only allows certain instruments. Add "${name}" to its allowed list and switch ${track.name} to it?`);
    if (!ok) { renderTracks(state.view); return; }
    return saveTrack(track.id, { instrumentId, allowInstrument: true });
  }
  return saveTrack(track.id, { instrumentId });
}

async function saveTrack(trackId, changes) {
  const view = state.view;
  try {
    const result = await state.api.updateTrack(view.projectId, trackId, { expectedRevision: view.revision, ...changes });
    state.ownRevisions.add(`${view.projectId}@${result.revision}`);
    await openProject(view.projectId);
  } catch (error) {
    if (error instanceof ApiError && error.code === "REVISION_CONFLICT") {
      await openProject(view.projectId, { notice: "The song changed meanwhile; reloaded the latest version. Please try again." });
    } else {
      showError(error);
      renderTracks(view);
    }
  }
}

function renderChecks(view) {
  const { errors, warnings } = view.validation;
  const items = [
    ...errors.map((i) => el("li", { class: "error-item", text: `✖ ${i.message}${i.trackId ? ` (${i.trackId})` : ""}` })),
    ...warnings.slice(0, 12).map((i) => el("li", { class: "warning-item", text: `⚠ ${i.message}${i.trackId ? ` (${i.trackId})` : ""}` })),
  ];
  if (warnings.length > 12) items.push(el("li", { class: "hint", text: `…and ${warnings.length - 12} more warnings` }));
  if (!items.length) items.push(el("li", { class: "ok-item", text: "✔ No problems found" }));
  $("issues").replaceChildren(...items);
  $("check-summary").textContent = `${errors.length} errors · ${warnings.length} warnings (advice, not mandatory)`;
}

function closeSong(note = "") {
  state.player.unload();
  state.view = null;
  $("song").hidden = true;
  $("welcome").hidden = false;
  $("welcome-note").textContent = note;
  $("welcome-note").hidden = !note;
  for (const item of $("project-list").children) item.classList.remove("active");
}

async function deleteSong() {
  const view = state.view;
  if (!view) return;
  const title = view.score.metadata.title;
  const ok = window.confirm(`Delete "${title}"?\n\nIt is moved to the trash folder on the NAS (data/trash) and can be recovered from there.`);
  if (!ok) return;
  try {
    await state.api.deleteProject(view.projectId);
    closeSong(`Deleted "${title}". It is in the trash folder on the NAS if you need it back.`);
    await refreshLibrary();
  } catch (error) {
    showError(error);
  }
}

// ------------------------------------------------------------------ exports

async function refreshExports() {
  const { exports } = await state.api.exports(state.view.projectId);
  $("export-list").replaceChildren(...exports.slice(0, 10).map((file) =>
    el("li", {},
      el("a", { href: state.api.url(file.downloadPath), download: file.file, text: file.file }),
      ` · ${(file.sizeBytes / 1024).toFixed(file.sizeBytes > 10240 ? 0 : 1)} KB`)));
}

async function createExport(format) {
  const status = $("export-status");
  status.textContent = format === "wav" || format === "mp3" ? "rendering…" : "exporting…";
  try {
    const options = { revision: state.view.revision };
    if (format === "mp3") options.bitrate = Number($("mp3-bitrate").value);
    const result = await state.api.createExport(state.view.projectId, format, options);
    status.textContent = `ready: ${result.file}`;
    await refreshExports();
  } catch (error) {
    status.textContent = "";
    showError(error);
  }
}

// ------------------------------------------------------------------- player

function setupPlayer() {
  const player = new Player({ api: state.api, audio: $("audio") });
  state.player = player;
  player.setVolume(Number($("volume").value));
  player.addEventListener("state", (e) => {
    const s = e.detail.state;
    $("player-state").textContent = s === "loading" ? "rendering…" : s;
    $("player-state").className = `pill ${s === "playing" ? "ok" : s === "loading" ? "busy" : ""}`;
    $("play").disabled = !["ready", "paused"].includes(s);
    $("pause").disabled = s !== "playing";
    $("stop").disabled = !["playing", "paused"].includes(s);
    $("speed").disabled = s === "loading" || !state.view;
  });
  player.addEventListener("position", (e) => {
    const { bar, beat, seconds, tick } = e.detail;
    $("bar").textContent = bar;
    $("beat").textContent = beat;
    $("time").textContent = formatTime(seconds);
    movePlayhead(tick);
  });
  player.addEventListener("loaded", () => {
    $("duration").textContent = formatTime(player.map.songSeconds());
    $("loop").checked = player.loop.enabled;
  });
  player.addEventListener("error", (e) => showError(e.detail.error));

  $("play").onclick = () => player.play().catch(showError);
  $("pause").onclick = () => player.pause();
  $("stop").onclick = () => player.stop();
  $("loop").onchange = (e) => player.setLoop(e.target.checked);
  $("volume").oninput = (e) => player.setVolume(Number(e.target.value));
  $("speed").replaceChildren(...SPEEDS.map((s) => el("option", { value: s, selected: s === 1, text: `${Math.round(s * 100)}%` })));
  $("speed").onchange = (e) => player.setSpeed(Number(e.target.value)).catch(() => {});
}

// --------------------------------------------------------------------- boot

async function enterApp(status) {
  $("login").hidden = true;
  $("app").hidden = false;
  $("logout").hidden = false;
  $("mcp-url").textContent = `${location.origin}${status.mcpPath}`;
  const audio = status.audio;
  $("engine").textContent = audio.available ? `Audio engine: ${audio.engine}` : `Audio engine unavailable: ${audio.error}`;
  setupPlayer();
  state.instruments = (await state.api.instruments()).instruments.filter((i) => i.available !== false);
  let searchTimer = null;
  $("search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => refreshLibrary().catch(showError), 200); };
  $("update-reload").onclick = () => openProject(state.view.projectId, {
    notice: state.pendingUpdate ? `Updated to revision ${state.pendingUpdate.revision}: ${state.pendingUpdate.summary}` : "",
  }).catch(showError);
  $("delete-song").onclick = () => deleteSong();
  for (const button of document.querySelectorAll("[data-export]")) {
    button.onclick = () => createExport(button.dataset.export);
  }
  openEvents();
  await refreshLibrary();
  const wanted = decodeURIComponent(location.hash.slice(1));
  if (wanted && state.projects.some((p) => p.projectId === wanted)) await openProject(wanted);
}

async function start() {
  $("login-form").onsubmit = async (event) => {
    event.preventDefault();
    $("login-error").hidden = true;
    try {
      const status = await connect($("token-input").value.trim());
      if (status) return enterApp(status);
      $("login-error").textContent = "That token was not accepted.";
    } catch (error) {
      $("login-error").textContent = `Cannot reach the server: ${error.message}`;
    }
    $("login-error").hidden = false;
  };
  $("logout").onclick = () => { setToken(""); location.reload(); };
  $("toast-close").onclick = () => showError(null);
  const saved = getToken();
  const status = saved ? await connect(saved).catch(() => null) : null;
  if (status) return enterApp(status);
  $("login").hidden = false;
}

start().catch(showError);
