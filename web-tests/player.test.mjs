// Unit tests for the browser player (run with: node --test web-tests/)
import assert from "node:assert/strict";
import { test } from "node:test";

import { Api, ApiError } from "../src/midimcp/web/api.js";
import { Player, TimeMap, formatTime } from "../src/midimcp/web/player.js";

// 6/8 at 84 BPM, 960 PPQ: 2880 ticks per bar, 8 bars.
const TIMING = { ppq: 960, tempoUsPerQuarter: 714286, ticksPerBar: 2880, totalTicks: 23040 };

function view({ revision = 3, loop = false } = {}) {
  return {
    projectId: "lanterns",
    revision,
    timing: TIMING,
    score: { timeline: { loop: { enabled: loop, startTick: 2880, endTick: 4 * 2880 } } },
  };
}

class FakeAudio extends EventTarget {
  constructor() {
    super();
    this.currentTime = 0;
    this.readyState = 0;
    this.paused = true;
    this.volume = 1;
    this._src = "";
  }
  set src(value) {
    this._src = value;
    this.readyState = 0;
    queueMicrotask(() => {
      this.readyState = 1;
      this.dispatchEvent(new Event("loadedmetadata"));
    });
  }
  get src() { return this._src; }
  async play() { this.paused = false; }
  pause() { this.paused = true; }
}

class FakeApi {
  constructor() { this.renders = []; this.token = "t"; }
  async render(id, options) {
    this.renders.push({ id, ...options });
    return { jobId: `j${this.renders.length}`, status: "queued" };
  }
  async waitForJob(job) {
    const speed = this.renders.at(-1).speed;
    return { ...job, status: "completed", downloadPath: `/api/renders/${job.jobId}-${speed}.wav`,
             render: { speed } };
  }
  url(path) { return `${path}?token=${this.token}`; }
}

function makePlayer() {
  const frames = [];
  const audio = new FakeAudio();
  const api = new FakeApi();
  const player = new Player({
    api, audio,
    raf: (cb) => { frames.push(cb); return frames.length; },
    cancelRaf: () => {},
  });
  const runFrame = () => { const cb = frames.shift(); if (cb) cb(); };
  return { player, audio, api, runFrame };
}

test("TimeMap converts ticks, seconds and bars", () => {
  const map = new TimeMap(TIMING, 1);
  assert.ok(Math.abs(map.tickToSeconds(2880) - 2.142858) < 1e-5);
  assert.equal(map.secondsToTick(map.tickToSeconds(23040)), 23040);
  assert.equal(map.barToTick(9), 23040);
  assert.deepEqual(map.position(2880 + 960 + 5), { bar: 2, beat: 2, tickInBar: 965 });
  const fast = new TimeMap(TIMING, 1.25);
  assert.ok(Math.abs(fast.songSeconds() - map.songSeconds() * 0.8) < 1e-9);
});

test("formatTime", () => {
  assert.equal(formatTime(0), "0:00");
  assert.equal(formatTime(68.57), "1:08");
  assert.equal(formatTime(-3), "0:00");
});

test("load renders at the current speed and becomes ready", async () => {
  const { player, audio, api } = makePlayer();
  const states = [];
  player.addEventListener("state", (e) => states.push(e.detail.state));
  await player.load(view());
  assert.deepEqual(api.renders, [{ id: "lanterns", revision: 3, speed: 1 }]);
  assert.equal(audio.src, "/api/renders/j1-1.wav?token=t");
  assert.deepEqual(states, ["loading", "ready"]);
});

test("play, pause, stop and seek", async () => {
  const { player, audio, runFrame } = makePlayer();
  const positions = [];
  player.addEventListener("position", (e) => positions.push(e.detail));
  await player.load(view());
  await player.play();
  assert.equal(player.state, "playing");
  assert.equal(audio.paused, false);
  audio.currentTime = player.map.tickToSeconds(2880 * 2);
  runFrame();
  assert.equal(positions.at(-1).bar, 3);
  player.pause();
  assert.equal(player.state, "paused");
  assert.equal(audio.paused, true);
  player.seekBar(5);
  assert.equal(player.tick, 4 * 2880);
  player.stop();
  assert.equal(player.state, "ready");
  assert.equal(player.tick, 0);
});

test("loop wraps from loop end to loop start while playing", async () => {
  const { player, audio, runFrame } = makePlayer();
  await player.load(view({ loop: true }));
  assert.equal(player.loop.enabled, true);
  await player.play();
  audio.currentTime = player.map.tickToSeconds(4 * 2880 + 10);
  runFrame();
  assert.equal(player.tick, 2880);
  player.setLoop(false);
  audio.currentTime = player.map.tickToSeconds(4 * 2880 + 10);
  runFrame();
  assert.equal(player.tick, 4 * 2880 + 10);
});

test("ended without loop returns to ready at the start", async () => {
  const { player, audio } = makePlayer();
  await player.load(view());
  await player.play();
  audio.currentTime = 30;
  audio.dispatchEvent(new Event("ended"));
  assert.equal(player.state, "ready");
  assert.equal(audio.currentTime, 0);
});

test("speed change re-renders and keeps the musical position and play state", async () => {
  const { player, audio, api } = makePlayer();
  await player.load(view());
  await player.play();
  player.seekBar(3);
  await player.setSpeed(1.25);
  assert.deepEqual(api.renders.at(-1), { id: "lanterns", revision: 3, speed: 1.25 });
  assert.equal(audio.src, "/api/renders/j2-1.25.wav?token=t");
  assert.equal(player.tick, 2 * 2880);
  assert.ok(Math.abs(audio.currentTime - player.map.tickToSeconds(5760)) < 1e-9);
  assert.equal(player.state, "playing");
});

test("a newer load wins over an older one still rendering", async () => {
  const { player, api } = makePlayer();
  let release;
  const slow = new Promise((resolve) => { release = resolve; });
  const original = api.waitForJob.bind(api);
  api.waitForJob = async (job) => { if (job.jobId === "j1") await slow; return original(job); };
  const first = player.load(view({ revision: 3 }));
  await player.load(view({ revision: 4 }));
  release();
  await first;
  assert.equal(player.view.revision, 4);
  assert.match(player.audio.src, /j2/);
});

test("render failure emits error and leaves player empty", async () => {
  const { player, api } = makePlayer();
  api.waitForJob = async () => { throw new ApiError(422, { code: "RENDER_BLOCKED", message: "x" }); };
  const errors = [];
  player.addEventListener("error", (e) => errors.push(e.detail.error.code));
  await assert.rejects(player.load(view()));
  assert.deepEqual(errors, ["RENDER_BLOCKED"]);
  assert.equal(player.state, "empty");
});

test("Api sends bearer token, parses errors, builds token URLs, polls jobs", async () => {
  const calls = [];
  const responses = [
    { ok: true, status: 200, body: { jobId: "j", status: "running" } },
    { ok: true, status: 200, body: { jobId: "j", status: "completed", downloadPath: "/x.wav" } },
    { ok: false, status: 409, body: { code: "REVISION_CONFLICT", message: "stale", currentRevision: 5 } },
  ];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    const r = responses.shift();
    return { ok: r.ok, status: r.status, json: async () => r.body };
  };
  const api = new Api({ token: "secret", fetchImpl });
  const done = await api.waitForJob({ jobId: "j", status: "queued" }, { sleep: async () => {} });
  assert.equal(done.status, "completed");
  assert.equal(calls[0].init.headers.Authorization, "Bearer secret");
  await assert.rejects(api.updateTrack("p", "t", { mute: true }), (error) => {
    assert.equal(error.status, 409);
    assert.equal(error.code, "REVISION_CONFLICT");
    assert.equal(error.body.currentRevision, 5);
    return true;
  });
  assert.equal(calls[2].init.method, "PATCH");
  assert.equal(JSON.parse(calls[2].init.body).mute, true);
  assert.equal(api.url("/api/renders/a.wav"), "/api/renders/a.wav?token=secret");
});
