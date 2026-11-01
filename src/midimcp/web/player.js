// Browser playback of server-rendered audio.
//
// The server renders a WAV per (revision, speed). Speed changes re-render at the
// scaled tempo, so pitch never changes; the player keeps the musical position
// (in ticks) across speed changes. Loop and seek work in ticks/bars.

export class TimeMap {
  /** @param timing project timing from the API; @param speed 1.0 = normal */
  constructor(timing, speed = 1) {
    this.ppq = timing.ppq;
    this.tempoUs = timing.tempoUsPerQuarter;
    this.ticksPerBar = timing.ticksPerBar;
    this.totalTicks = timing.totalTicks;
    this.speed = speed;
  }

  secondsPerTick() {
    return this.tempoUs / 1e6 / this.ppq / this.speed;
  }

  tickToSeconds(tick) {
    return tick * this.secondsPerTick();
  }

  secondsToTick(seconds) {
    return Math.max(0, Math.round(seconds / this.secondsPerTick()));
  }

  barToTick(bar) {
    return (bar - 1) * this.ticksPerBar;
  }

  /** 1-based bar and 1-based beat-in-bar (quarter notes) for display. */
  position(tick) {
    const bar = Math.floor(tick / this.ticksPerBar) + 1;
    const inBar = tick % this.ticksPerBar;
    return { bar, beat: Math.floor(inBar / this.ppq) + 1, tickInBar: inBar };
  }

  songSeconds() {
    return this.tickToSeconds(this.totalTicks);
  }
}

export function formatTime(seconds) {
  const s = Math.max(0, seconds);
  const minutes = Math.floor(s / 60);
  const rest = Math.floor(s % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export const SPEEDS = [0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5];

/**
 * Events: "state" ({state}), "position" ({tick, seconds, bar, beat}), "loading" ({speed}),
 * "loaded" ({render}), "error" ({error}).
 * States: "empty" | "loading" | "ready" | "playing" | "paused".
 */
export class Player extends EventTarget {
  constructor({ api, audio, raf = defaultRaf, cancelRaf = defaultCancelRaf }) {
    super();
    this.api = api;
    this.audio = audio;
    this.raf = raf;
    this.cancelRaf = cancelRaf;
    this.state = "empty";
    this.speed = 1;
    this.view = null;
    this.map = null;
    this.loop = { enabled: false, startTick: 0, endTick: 0 };
    this._frame = null;
    this._loadToken = 0;
    audio.addEventListener("ended", () => this._onEnded());
  }

  /**
   * Load a project view (from api.project) and render it at the current speed.
   * With the loop on, the server renders exactly the loop section (no decay tail) and the
   * browser repeats it gaplessly - what a game engine would do. Otherwise the whole song.
   */
  async load(view, { speed = this.speed, keepTick = null, autoplay = false, loop = null } = {}) {
    const loadToken = ++this._loadToken;
    this.pause();
    const sameSong = this.view && this.view.projectId === view.projectId;
    this.view = view;
    this.speed = speed;
    this.map = new TimeMap(view.timing, speed);
    const songLoop = view.score.timeline.loop;
    const enabled = loop ?? (sameSong ? this.loop.enabled : songLoop.enabled);
    this.loop = songLoop.enabled
      ? { enabled, startTick: songLoop.startTick, endTick: songLoop.endTick }
      : { enabled, startTick: 0, endTick: view.timing.totalTicks };
    this.offsetTick = 0;
    this._setState("loading");
    this._emit("loading", { speed });
    try {
      const options = { revision: view.revision, speed };
      if (this.loop.enabled) options.loop = true;
      const job = await this.api.render(view.projectId, options);
      const done = await this.api.waitForJob(job);
      if (loadToken !== this._loadToken) return; // superseded by a newer load
      this.audio.loop = this.loop.enabled;
      this.audio.src = this.api.url(done.downloadPath);
      this.render = done.render;
      this.offsetTick = done.render?.startTick ?? 0;
      await whenMetadata(this.audio);
      this.seekTick(keepTick ?? (this.loop.enabled ? this.loop.startTick : 0));
      this._setState("ready");
      this._emit("loaded", { render: done.render });
      this._emitPosition();
      if (autoplay) await this.play();
    } catch (error) {
      if (loadToken !== this._loadToken) return;
      this._setState("empty");
      this._emit("error", { error });
      throw error;
    }
  }

  /** Stop and forget the current song (e.g. after it was deleted). */
  unload() {
    this._loadToken++;
    this.audio.pause();
    this._stopFrames();
    this.audio.removeAttribute("src");
    if (typeof this.audio.load === "function") this.audio.load();
    this.view = null;
    this.map = null;
    this._setState("empty");
  }

  get tick() {
    if (!this.map) return 0;
    const tick = (this.offsetTick || 0) + this.map.secondsToTick(this.audio.currentTime);
    return this.loop.enabled ? Math.min(tick, this.loop.endTick) : tick;
  }

  async play() {
    if (!["ready", "paused"].includes(this.state)) return;
    await this.audio.play();
    this._setState("playing");
    this._tick();
  }

  pause() {
    if (this.state !== "playing") return;
    this.audio.pause();
    this._setState("paused");
    this._stopFrames();
    this._emitPosition();
  }

  stop() {
    if (!["playing", "paused", "ready"].includes(this.state)) return;
    this.audio.pause();
    this.seekTick(this.loop.enabled ? this.loop.startTick : 0);
    this._setState("ready");
    this._stopFrames();
    this._emitPosition();
  }

  seekTick(tick) {
    if (!this.map) return;
    let target = Math.min(Math.max(0, tick), this.map.totalTicks);
    if (this.loop.enabled) {
      target = Math.min(Math.max(target, this.loop.startTick), this.loop.endTick - 1);
    }
    this.audio.currentTime = this.map.tickToSeconds(target - (this.offsetTick || 0));
    this._emitPosition();
  }

  seekBar(bar) {
    this.seekTick(this.map.barToTick(bar));
  }

  /** Switch between the seamless loop render and the full song (re-renders, keeps position). */
  async setLoop(enabled) {
    enabled = Boolean(enabled);
    if (!this.view || enabled === this.loop.enabled) {
      this.loop.enabled = enabled;
      return;
    }
    const wasPlaying = this.state === "playing";
    await this.load(this.view, { speed: this.speed, keepTick: this.tick, autoplay: wasPlaying, loop: enabled });
  }

  setVolume(volume) {
    this.audio.volume = Math.min(1, Math.max(0, volume));
  }

  /** Re-render at another speed, keeping the musical position and play state. */
  async setSpeed(speed) {
    if (!this.view || speed === this.speed) return;
    const wasPlaying = this.state === "playing";
    await this.load(this.view, { speed, keepTick: this.tick, autoplay: wasPlaying });
  }

  /** Called every animation frame while playing: emits position, enforces the loop. */
  _tick() {
    this._stopFrames();
    const step = () => {
      if (this.state !== "playing") return;
      this._emitPosition();
      this._frame = this.raf(step);
    };
    this._frame = this.raf(step);
  }

  _onEnded() {
    // With the loop on, audio.loop repeats the loop render and "ended" never fires.
    this._setState("ready");
    this._stopFrames();
    this.seekTick(0);
    this._emitPosition();
  }

  _stopFrames() {
    if (this._frame !== null) this.cancelRaf(this._frame);
    this._frame = null;
  }

  _emitPosition() {
    if (!this.map) return;
    const tick = Math.min(this.tick, this.map.totalTicks);
    this._emit("position", { tick, seconds: this.audio.currentTime, ...this.map.position(tick) });
  }

  _setState(state) {
    this.state = state;
    this._emit("state", { state });
  }

  _emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }
}

function whenMetadata(audio) {
  if (audio.readyState >= 1) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const ok = () => { cleanup(); resolve(); };
    const fail = () => { cleanup(); reject(new Error("audio failed to load")); };
    const cleanup = () => {
      audio.removeEventListener("loadedmetadata", ok);
      audio.removeEventListener("error", fail);
    };
    audio.addEventListener("loadedmetadata", ok);
    audio.addEventListener("error", fail);
  });
}

function defaultRaf(callback) {
  return globalThis.requestAnimationFrame
    ? globalThis.requestAnimationFrame(callback)
    : setTimeout(callback, 16);
}

function defaultCancelRaf(handle) {
  if (globalThis.cancelAnimationFrame) globalThis.cancelAnimationFrame(handle);
  else clearTimeout(handle);
}
