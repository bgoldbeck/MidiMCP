// MidiMCP web UI (beginner mode): library, transport, overview, tracks, checks, exports.
// All text from songs is inserted with textContent / DOM nodes, never as HTML.
import { Api, ApiError, getToken, setToken } from "./api.js";
import { Player, SPEEDS, formatTime } from "./player.js";
import { copyText, flashCopyResult } from "./clipboard.js";
import { setupTemplates } from "./templates-view.js";
import { NoteEditor } from "./editor.js";
import { sourceOptions, samplerBinding } from "./sampler-view.js";

const $ = (id) => document.getElementById(id);
const COLORS = ["#d9a441", "#8fbf6a", "#6aa6d9", "#d97a6a", "#b48ad9", "#6ad9c4", "#d9d06a", "#d96ab0"];
const SVG_NS = "http://www.w3.org/2000/svg";

const state = {
  api: null,
  player: null,
  editor: null,
  projectLoad: 0,
  requestedProject: null,
  projects: [],
  view: null,
  instruments: [],
  patches: [],
  pendingUpdate: null,
  socket: null,
  ownRevisions: new Set(), // revisions this page created; their events are not "news"
  org: { favorites: [], collections: [] }, // favorites + the user's collections
  filter: "all", // "all" | "favorites" | a collection id
  sort: "recent",
};

const prefs = {
  get(key, fallback) {
    try { return localStorage.getItem(`midimcp.${key}`) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(`midimcp.${key}`, value); } catch { /* storage unavailable */ }
  },
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
    refreshOrganization().then(() => refreshLibrary()).catch(() => {});
    if (state.view?.projectId === event.projectId) closeSong("This song was deleted (it is in the trash folder on the NAS).");
    return;
  }
  if (event.type === "library.organized") {
    refreshOrganization().then(() => refreshLibrary()).catch(() => {});
    if (state.view) renderSongOrganization(state.view.projectId).catch(() => {});
    return;
  }
  if (event.type !== "project.updated") return;
  refreshLibrary().catch(() => {});
  const view = state.view;
  if (!view || event.projectId !== view.projectId || event.revision <= view.revision) return;
  if (state.requestedProject !== view.projectId) return; // a navigation is already in progress
  if (state.ownRevisions.has(`${event.projectId}@${event.revision}`)) return; // our own save
  const who = event.author === "agent" ? "an AI agent" : event.author;
  state.pendingUpdate = event;
  if (state.player.state === "playing" || state.editor?.hasPendingWork()) {
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
  if (!["all", "favorites"].includes(state.filter) && !state.org.collections.some((c) => c.id === state.filter)) {
    state.filter = "all"; // that collection was deleted
  }
  renderFilters();
  const shown = sortSongs(projects.filter((p) => state.filter === "all"
    || (state.filter === "favorites" ? p.favorite : p.collections.includes(state.filter))));
  const names = new Map(state.org.collections.map((c) => [c.id, c.name]));
  const list = $("project-list");
  list.replaceChildren(...shown.map((p) => el("li", {
    class: `song${state.view?.projectId === p.projectId ? " active" : ""}`,
    "data-project": p.projectId,
    onclick: () => openProject(p.projectId).catch(showError),
  },
  starButton(p.projectId, p.favorite),
  el("span", { class: "text" },
    el("span", { class: "title", text: p.title }),
    p.collections.length ? el("span", { class: "sub" }, ...p.collections.map((id) => el("span", { class: "badge", text: names.get(id) || id }))) : null,
    el("span", { class: "sub", text: [p.usage, `rev ${p.headRevision}`, relativeTime(p.updatedAt)].filter(Boolean).join(" · ") })))));
  const empty = $("library-empty");
  if (projects.length === 0 && !search) {
    empty.textContent = "No songs yet. Ask your AI client to compose one; it appears here automatically.";
  } else if (shown.length === 0 && state.filter === "favorites") {
    empty.textContent = "No favorites yet. Click ☆ next to a song to star it.";
  } else if (shown.length === 0 && state.filter !== "all") {
    empty.textContent = "No songs in this collection yet. Open a song and tick this collection under its title.";
  } else {
    empty.textContent = "";
  }
  empty.hidden = !empty.textContent;
}

function sortSongs(songs) {
  const byTitle = (a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
  const byRecent = (a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || "");
  const copy = [...songs];
  if (state.sort === "title") return copy.sort(byTitle);
  if (state.sort === "favorites") return copy.sort((a, b) => (b.favorite - a.favorite) || byRecent(a, b));
  return copy.sort(byRecent);
}

function starButton(projectId, favorite, extraClass = "") {
  return el("button", {
    class: `star${favorite ? " on" : ""}${extraClass}`,
    title: favorite ? "Remove from favorites" : "Add to favorites",
    "aria-label": favorite ? "Remove from favorites" : "Add to favorites",
    "aria-pressed": favorite ? "true" : "false",
    onclick: (event) => { event.stopPropagation(); setFavorite(projectId, !favorite); },
  }, favorite ? "★" : "☆");
}

// ------------------------------------------------------------ organization

async function refreshOrganization() {
  state.org = await state.api.collections();
}

function renderFilters() {
  const favorites = state.org.favorites.length;
  const chips = [
    ["all", "All songs", null],
    ["favorites", "★ Favorites", favorites],
    ...state.org.collections.map((c) => [c.id, c.name, c.count]),
  ];
  $("library-filters").replaceChildren(...chips.map(([id, label, count]) => el("button", {
    class: `chip${state.filter === id ? " active" : ""}`,
    "data-filter": id,
    "aria-pressed": state.filter === id ? "true" : "false",
    onclick: () => { state.filter = id; prefs.set("filter", id); refreshLibrary().catch(showError); },
  }, label, count === null ? null : el("span", { class: "count", text: String(count) }))));
  $("collection-actions").hidden = ["all", "favorites"].includes(state.filter);
}

async function setFavorite(projectId, favorite) {
  try {
    await state.api.setOrganization(projectId, { favorite });
    await refreshOrganization();
    await refreshLibrary();
    if (state.view?.projectId === projectId) await renderSongOrganization(projectId);
  } catch (error) {
    showError(error);
  }
}

async function renderSongOrganization(projectId) {
  const mine = await state.api.organization(projectId);
  if (state.view?.projectId !== projectId) return; // another song was opened meanwhile
  const star = $("favorite-song");
  star.textContent = mine.favorite ? "★" : "☆";
  star.classList.toggle("on", mine.favorite);
  star.setAttribute("aria-pressed", mine.favorite ? "true" : "false");
  star.title = mine.favorite ? "Remove from favorites" : "Add to favorites";
  star.onclick = () => setFavorite(projectId, !mine.favorite);
  const names = state.org.collections.filter((c) => mine.collections.includes(c.id)).map((c) => c.name);
  $("song-collections-label").textContent = names.length ? names.join(", ") : "none";
  const boxes = state.org.collections.map((c) => el("label", {},
    el("input", {
      type: "checkbox",
      "data-collection": c.id,
      checked: mine.collections.includes(c.id),
      onchange: () => saveSongCollections(projectId),
    }), ` ${c.name}`));
  $("song-collections-list").replaceChildren(
    ...(boxes.length ? boxes : [el("p", { class: "hint", text: "No collections yet." })]),
    el("button", { class: "secondary small new", onclick: () => newCollection(projectId) }, "+ New collection…"));
}

async function saveSongCollections(projectId) {
  const ids = [...$("song-collections-list").querySelectorAll("input[data-collection]:checked")].map((i) => i.dataset.collection);
  try {
    await state.api.setOrganization(projectId, { collections: ids });
    await refreshOrganization();
    await refreshLibrary();
    await renderSongOrganization(projectId);
  } catch (error) {
    showError(error);
  }
}

/** Ask for a name and create a collection; with ``projectId`` also put that song in it. */
async function newCollection(projectId = null) {
  const name = window.prompt("Name for the new collection (e.g. Town themes, Boss fights):");
  if (!name || !name.trim()) return;
  try {
    const created = await state.api.createCollection(name.trim());
    if (projectId) {
      const mine = await state.api.organization(projectId);
      await state.api.setOrganization(projectId, { collections: [...mine.collections, created.id] });
    } else {
      state.filter = created.id;
      prefs.set("filter", created.id);
    }
    await refreshOrganization();
    await refreshLibrary();
    if (state.view) await renderSongOrganization(state.view.projectId);
  } catch (error) {
    showError(error);
  }
}

async function renameCollection() {
  const current = state.org.collections.find((c) => c.id === state.filter);
  if (!current) return;
  const name = window.prompt("New name for this collection:", current.name);
  if (!name || !name.trim() || name.trim() === current.name) return;
  try {
    await state.api.renameCollection(current.id, name.trim());
    await refreshOrganization();
    await refreshLibrary();
    if (state.view) await renderSongOrganization(state.view.projectId);
  } catch (error) {
    showError(error);
  }
}

async function deleteCollection() {
  const current = state.org.collections.find((c) => c.id === state.filter);
  if (!current) return;
  if (!window.confirm(`Delete the collection "${current.name}"? The songs in it are kept.`)) return;
  try {
    await state.api.deleteCollection(current.id);
    state.filter = "all";
    prefs.set("filter", "all");
    await refreshOrganization();
    await refreshLibrary();
    if (state.view) await renderSongOrganization(state.view.projectId);
  } catch (error) {
    showError(error);
  }
}

// ------------------------------------------------------------------ project

async function openProject(projectId, { notice = "" } = {}) {
  const request = ++state.projectLoad;
  state.requestedProject = projectId;
  showError(null);
  const sameSong = state.view?.projectId === projectId;
  const keepTick = sameSong ? state.player.tick : 0;
  const resume = sameSong && state.player.wantsPlayback; // e.g. instrument changed mid-song
  let view;
  try {
    view = await state.api.project(projectId);
  } catch (error) {
    if (request === state.projectLoad) state.requestedProject = state.view?.projectId ?? null;
    throw error;
  }
  if (request !== state.projectLoad) return;
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
  state.editor?.setView(view);
  refreshExports().catch(() => {});
  renderSongOrganization(projectId).catch(() => {});
  for (const item of $("project-list").children) {
    item.classList.toggle("active", item.dataset.project === projectId);
  }
  await state.player.load(view, { speed: Number($("speed").value), keepTick, autoplay: resume }).catch(() => {});
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
    const sourceSelect = el("select", {
      disabled: wholeLock || track.isPercussion,
      "aria-label": `Sound source for ${track.name}`,
      onchange: e => {
        try { saveTrack(track.id, {sampler:samplerBinding(e.target.value,state.patches)}); }
        catch (error) { showError(error); renderTracks(state.view); }
      },
    }, sourceOptions(track,state.patches).map(o => el("option", {value:o.value,text:o.label,selected:o.selected,disabled:o.disabled})));
    const patch = state.patches.find(p => p.id === track.sampler?.patchId);
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
      el("td", {class:"track-source"},
        el("label", {}, "Sound source", sourceSelect), resetButton(track, "sampler", wholeLock),
        el("label", {}, track.sampler ? "MIDI fallback instrument" : "Instrument", instrumentSelect), resetButton(track, "instrument", wholeLock),
        track.sampler ? el("small", {class:"hint",text:patch?.description || "Sampled sound is preserved in WAV/MP3. MIDI uses the fallback instrument."}) : null),
      el("td", {}, volume, db, resetButton(track, "volume", wholeLock)),
      el("td", {}, mute),
      el("td", {}, `${track.notes.length} `, el("button", {
        class: "secondary small", text: "Edit notes", "aria-label": `Edit notes in ${track.name}`,
        onclick: () => showEditor(track.id),
      })),
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
  ["synth", "Synth leads (chiptune)"],
  ["pad", "Pads"],
  ["bass", "Bass"],
  ["percussion-melodic", "Timpani & tuned drums"],
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
  if (JSON.stringify(d.sampler ?? null) !== JSON.stringify(track.sampler ?? null)) fields.push("sampler");
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
    sampler: `sound source → ${d.sampler ? state.patches.find(p=>p.id===d.sampler.patchId)?.name || d.sampler.patchId : "Project GM bank"}`,
  };
  const label = what === "all" ? "Reset" : "↺";
  return el("button", {
    class: what === "all" ? "secondary small" : "icon-button",
    title: `Back to default (revision ${d.revision}): ${fields.map((f) => parts[f]).join(", ")}`,
    "aria-label": `Reset ${what === "all" ? "track" : what === "sampler" ? "sound source" : what} of ${track.name} to default`,
    "data-reset": what,
    onclick: () => resetTrack(track.id, fields),
  }, label);
}

async function resetTrack(trackId, fields) {
  const view = state.view;
  try {
    const result = await state.api.resetTrack(view.projectId, trackId, { expectedRevision: view.revision, fields });
    state.ownRevisions.add(`${view.projectId}@${result.revision}`);
    if (state.view?.projectId === view.projectId && state.requestedProject === view.projectId) await openProject(view.projectId);
  } catch (error) {
    if (error instanceof ApiError && error.code === "REVISION_CONFLICT") {
      if (state.view?.projectId === view.projectId && state.requestedProject === view.projectId) await openProject(view.projectId, { notice: "The song changed meanwhile; reloaded the latest version. Please try again." });
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
    if (state.view?.projectId === view.projectId && state.requestedProject === view.projectId) await openProject(view.projectId);
  } catch (error) {
    if (error instanceof ApiError && error.code === "REVISION_CONFLICT") {
      if (state.view?.projectId === view.projectId && state.requestedProject === view.projectId) await openProject(view.projectId, { notice: "The song changed meanwhile; reloaded the latest version. Please try again." });
    } else {
      showError(error);
      if (state.view?.projectId === view.projectId && state.requestedProject === view.projectId) renderTracks(state.view);
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
  state.projectLoad++;
  state.requestedProject = null;
  state.player.unload();
  state.editor?.setView(null);
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

const FORMAT_LABELS = { mp3: "MP3", wav: "WAV", midi: "MIDI", json: "Project JSON" };

async function refreshExports() {
  const { exports } = await state.api.exports(state.view.projectId);
  $("export-list-title").hidden = exports.length === 0;
  $("export-list").replaceChildren(...exports.slice(0, 10).map((file) =>
    el("li", {},
      el("a", { class: "download-link", href: state.api.url(file.downloadPath), download: file.file, text: `⬇ ${file.file}` }),
      el("span", { class: "hint", text: ` ${formatSize(file.sizeBytes)}` }))));
}

function formatSize(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(bytes > 10240 ? 0 : 1)} KB`;
}

/** Save a finished export to the user's computer (the server sends it as an attachment). */
function saveToComputer(result) {
  const link = el("a", { href: state.api.url(result.downloadPath), download: result.file, hidden: true });
  document.body.append(link);
  link.click();
  link.remove();
}

/** Create an export of the current revision and download it. Returns the export, or null. */
async function createExport(format, { bitrate, statusId = "export-status" } = {}) {
  const status = $(statusId);
  const label = FORMAT_LABELS[format] || format;
  status.textContent = format === "wav" || format === "mp3" ? `preparing ${label} (rendering audio)…` : `preparing ${label}…`;
  try {
    const options = { revision: state.view.revision };
    if (format === "mp3") options.bitrate = bitrate || Number($("mp3-bitrate").value);
    const result = await state.api.createExport(state.view.projectId, format, options);
    saveToComputer(result);
    status.textContent = `downloaded: ${result.file}`;
    if (result.warnings?.length) showError(new Error(result.warnings.map(w=>w.message).join(" ")));
    await refreshExports();
    return result;
  } catch (error) {
    status.textContent = "";
    showError(error);
    return null;
  }
}

async function downloadSong() {
  const button = $("download-song");
  const [format, bitrate] = $("download-format").value.split(":");
  button.disabled = true;
  try {
    await createExport(format, { bitrate: bitrate ? Number(bitrate) : undefined, statusId: "download-status" });
  } finally {
    button.disabled = false;
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
    state.editor?.setPosition(tick);
  });
  player.addEventListener("loaded", e => {
    if (e.detail.render?.clippedSamples > 0) showError(new Error("The mix clipped. Lower the track volumes and render again."));
  });
  player.addEventListener("loaded", () => {
    $("duration").textContent = formatTime(player.map.songSeconds());
    $("loop").checked = player.loop.enabled;
    $("selection-preview").hidden = !player.previewRange;
  });
  player.addEventListener("error", (e) => showError(e.detail.error));

  $("play").onclick = () => player.play().catch(showError);
  $("pause").onclick = () => player.pause();
  $("stop").onclick = () => player.stop();
  $("loop").onchange = (e) => player.setLoop(e.target.checked).catch(() => {});
  $("volume").oninput = (e) => player.setVolume(Number(e.target.value));
  $("speed").replaceChildren(...SPEEDS.map((s) => el("option", { value: s, selected: s === 1, text: `${Math.round(s * 100)}%` })));
  $("speed").onchange = (e) => player.setSpeed(Number(e.target.value)).catch(() => {});
  $("end-selection-preview").onclick = () => player.clearPreviewRegion().catch(showError);
}

function showEditor(trackId = null) {
  $("note-editor-panel").hidden = false;
  $("toggle-note-editor").setAttribute("aria-expanded", "true");
  if (trackId) state.editor.selectTrack(trackId);
  $("note-editor").scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function setupEditor() {
  state.editor = new NoteEditor({
    container: $("note-editor-panel"), api: state.api,
    onChange: async ({ projectId, revision }) => {
      state.ownRevisions.add(`${projectId}@${revision}`);
      if (state.view?.projectId === projectId && state.requestedProject === projectId) await openProject(projectId);
      await refreshLibrary();
    },
    onPreview: ({ startTick, endTick }) => state.player.previewRegion(startTick, endTick).catch(showError),
    onSeek: (tick) => state.player.seekTick(tick),
    onError: (error) => {
      showError(error);
      if (error.code === "REVISION_CONFLICT" && state.view && state.requestedProject === state.view.projectId) {
        openProject(state.view.projectId, { notice: "The song changed; reloaded the latest revision. Your unsaved edit was not applied." }).catch(showError);
      }
    },
  });
  $("toggle-note-editor").onclick = () => {
    const panel = $("note-editor-panel");
    panel.hidden = !panel.hidden;
    $("toggle-note-editor").setAttribute("aria-expanded", String(!panel.hidden));
  };
}

// --------------------------------------------------------------------- boot

async function enterApp(status) {
  $("login").hidden = true;
  $("app").hidden = false;
  $("logout").hidden = false;
  $("mcp-url").textContent = `${location.origin}${status.mcpPath}`;
  for (const client of ["antigravity", "claude", "codex"]) {
    $(`config-${client}`).href = state.api.url(`/api/mcp-config?client=${client}`);
  }
  $("config-tools").href = state.api.url("/api/mcp-tools?download=1");
  $("copy-claude-command").onclick = async (event) => {
    try {
      const { claudeCommand } = await state.api.request("GET", "/api/mcp-connect");
      flashCopyResult(event.target, await copyText(claudeCommand), "Copy Claude Code command");
    } catch (error) {
      showError(error);
    }
  };
  const audio = status.audio;
  $("engine").textContent = audio.available ? `Audio engines: ${[audio.engine, audio.samplerAvailable ? "sfizz sampled instruments" : null].filter(Boolean).join(" · ")}` : `Audio engine unavailable: ${audio.error}`;
  setupPlayer();
  setupEditor();
  const [instruments, patches] = await Promise.allSettled([state.api.instruments(), state.api.samplerPatches()]);
  if (instruments.status === "fulfilled") state.instruments = instruments.value.instruments.filter(i=>i.available !== false);
  else showError(instruments.reason);
  if (patches.status === "fulfilled") state.patches = patches.value.patches.map(p => ({...p,available:p.available && audio.samplerAvailable !== false}));
  else showError(patches.reason);
  state.filter = prefs.get("filter", "all");
  state.sort = prefs.get("sort", "recent");
  $("library-sort").value = state.sort;
  $("library-sort").onchange = () => {
    state.sort = $("library-sort").value;
    prefs.set("sort", state.sort);
    refreshLibrary().catch(showError);
  };
  $("new-collection").onclick = () => newCollection();
  $("rename-collection").onclick = () => renameCollection();
  $("delete-collection").onclick = () => deleteCollection();
  await refreshOrganization().catch(() => {});
  let searchTimer = null;
  $("search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => refreshLibrary().catch(showError), 200); };
  $("update-reload").onclick = () => openProject(state.view.projectId, {
    notice: state.pendingUpdate ? `Updated to revision ${state.pendingUpdate.revision}: ${state.pendingUpdate.summary}` : "",
  }).catch(showError);
  $("delete-song").onclick = () => deleteSong();
  $("download-song").onclick = () => downloadSong();
  try {
    const saved = localStorage.getItem("midimcp.downloadFormat");
    if (saved && [...$("download-format").options].some((o) => o.value === saved)) $("download-format").value = saved;
  } catch { /* storage unavailable: keep the default */ }
  $("download-format").onchange = () => {
    try { localStorage.setItem("midimcp.downloadFormat", $("download-format").value); } catch { /* ignore */ }
  };
  for (const button of document.querySelectorAll("[data-export]")) {
    button.onclick = () => createExport(button.dataset.export);
  }
  const templates = setupTemplates({ api: state.api, el, showError, instrumentName });
  $("tabs").hidden = false;
  const showView = (view) => {
    for (const t of document.querySelectorAll("#tabs .tab[data-view]")) t.classList.toggle("active", t.dataset.view === view);
    $("app").hidden = view !== "songs";
    $("templates-view").hidden = view !== "templates";
    if (view === "templates") templates.refreshList().catch(showError);
    history.replaceState(null, "", view === "templates" ? "#templates" : location.pathname);
  };
  for (const tab of document.querySelectorAll("#tabs .tab[data-view]")) {
    tab.onclick = () => showView(tab.dataset.view);
  }
  if (location.hash === "#templates") showView("templates");
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
