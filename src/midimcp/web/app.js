// MidiMCP browser player (feature 12). Feature 13 grows this into the full UI.
import { Api, ApiError, getToken, setToken } from "./api.js";
import { Player, SPEEDS, formatTime } from "./player.js";

const $ = (id) => document.getElementById(id);
let api = null;
let player = null;
let currentView = null;

function show(id, visible) { $(id).hidden = !visible; }

function showError(error) {
  const box = $("error");
  if (!error) { box.hidden = true; return; }
  box.textContent = error instanceof ApiError ? `${error.code}: ${error.message}` : String(error.message || error);
  box.hidden = false;
}

async function connect(token) {
  const candidate = new Api({ token });
  try {
    await candidate.status();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return false;
    throw error;
  }
  api = candidate;
  setToken(token);
  return true;
}

function setupPlayer() {
  player = new Player({ api, audio: $("audio") });
  player.setVolume(Number($("volume").value));
  player.addEventListener("state", (e) => {
    const state = e.detail.state;
    $("player-state").textContent = state === "loading" ? "rendering…" : state;
    $("player-state").className = `pill ${state === "playing" ? "ok" : state === "loading" ? "busy" : ""}`;
    $("play").disabled = !["ready", "paused"].includes(state);
    $("pause").disabled = state !== "playing";
    $("stop").disabled = !["playing", "paused"].includes(state);
    $("seek").disabled = ["empty", "loading"].includes(state);
    $("speed").disabled = state === "loading" || !currentView;
  });
  player.addEventListener("position", (e) => {
    const { bar, beat, seconds } = e.detail;
    $("bar").textContent = bar;
    $("beat").textContent = beat;
    $("time").textContent = formatTime(seconds);
    if (document.activeElement !== $("seek")) $("seek").value = bar;
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
  $("seek").oninput = (e) => player.seekBar(Number(e.target.value));
  $("speed").onchange = (e) => player.setSpeed(Number(e.target.value)).catch(() => {});
  $("speed").innerHTML = SPEEDS.map((s) => `<option value="${s}" ${s === 1 ? "selected" : ""}>${Math.round(s * 100)}%</option>`).join("");
}

async function loadProjects() {
  const { projects } = await api.projects();
  const select = $("project-select");
  if (!projects.length) {
    select.innerHTML = `<option value="">No songs yet – ask your AI client to compose one</option>`;
    return;
  }
  select.innerHTML = `<option value="">Choose a song…</option>` + projects
    .map((p) => `<option value="${encodeURIComponent(p.projectId)}">${escapeHtml(p.title)} (rev ${p.headRevision})</option>`)
    .join("");
}

async function openProject(projectId) {
  showError(null);
  if (!projectId) return;
  currentView = await api.project(projectId);
  const t = currentView.timing;
  const key = currentView.score.tonality;
  $("song-meta").textContent = `${t.quarterNoteBpm} BPM · ${t.meter} · ${key.displaySpelling} ${key.mode} · ${t.bars} bars · revision ${currentView.revision}`;
  $("seek").max = Math.max(1, Math.ceil(t.bars));
  await player.load(currentView, { speed: Number($("speed").value) }).catch(() => {});
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function start() {
  $("login-form").onsubmit = async (event) => {
    event.preventDefault();
    $("login-error").hidden = true;
    try {
      if (await connect($("token-input").value.trim())) return enterApp();
      $("login-error").textContent = "That token was not accepted.";
    } catch (error) {
      $("login-error").textContent = `Cannot reach the server: ${error.message}`;
    }
    $("login-error").hidden = false;
  };
  $("logout").onclick = () => { setToken(""); location.reload(); };

  const saved = getToken();
  if (saved && (await connect(saved).catch(() => false))) return enterApp();
  show("login", true);
}

async function enterApp() {
  show("login", false);
  show("app", true);
  show("logout", true);
  $("connection").textContent = "connected";
  $("connection").className = "pill ok";
  setupPlayer();
  $("project-select").onchange = (e) => openProject(decodeURIComponent(e.target.value)).catch(showError);
  await loadProjects();
}

start().catch(showError);
