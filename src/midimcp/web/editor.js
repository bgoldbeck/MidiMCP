import { bounds, locked, move, resize, scale, boxSelect, snap, prompt } from "./editor-model.js";
import { copyText } from "./clipboard.js";
const NS = "http://www.w3.org/2000/svg";
function el(tag, text, attrs = {}) {
  const n = document.createElement(tag);
  if (text) n.textContent = text;
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}
function svg(tag, attrs) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}
export class NoteEditor {
  constructor({ container, api, onChange = () => {
  }, onPreview = () => {
  }, onSeek = () => {
  }, onError = () => {
  } }) {
    Object.assign(this, { container, api, onChange, onPreview, onSeek, onError });
    this.selected = /* @__PURE__ */ new Set();
    this.undo = [];
    this.redo = [];
    this.zoom = 1;
    this.mode = "piano";
    this.pending = false;
    this.position = 0;
    this.generation = 0;
    this.allowExtension = false;
    this.message = "";
    container.classList.add("note-editor");
    container.tabIndex = 0;
    this.keyHandler = (e) => this.key(e);
    container.addEventListener("keydown", this.keyHandler);
  }
  destroy() {
    this.cancel();
    this.container.removeEventListener("keydown", this.keyHandler);
    this.container.replaceChildren();
  }
  hasPendingWork() {
    return this.pending;
  }
  setPosition(tick) {
    this.position = tick;
    this.cursor?.setAttribute("x1", this.x(tick));
    this.cursor?.setAttribute("x2", this.x(tick));
  }
  setView(view) {
    this.cancel();
    const same = !!view && this.view?.projectId === view.projectId;
    if (!same) {
      this.generation++;
      this.scroll = null;
      this.message = "";
      this.ownRevision = undefined;
    }
    if (!same || view?.revision !== this.view?.revision && view.revision !== this.ownRevision) {
      if (same) this.generation++;
      this.undo = [];
      this.redo = [];
    }
    if (!same) this.selected.clear();
    this.view = view;
    if (!view) {
      this.cursor = null;
      this.status = null;
      this.container.replaceChildren();
      return;
    }
    if (!view.score.tracks.some((t) => t.id === this.trackId)) this.trackId = view.score.tracks[0]?.id;
    const ids = new Set(this.notes.map((n) => n.id));
    this.selected = new Set([...this.selected].filter((id) => ids.has(id)));
    this.render();
  }
  get track() {
    return this.view?.score.tracks.find((t) => t.id === this.trackId);
  }
  get notes() {
    return this.track?.notes || [];
  }
  get selection() {
    return this.notes.filter((n) => this.selected.has(n.id));
  }
  get locks() {
    return this.view?.brief?.locks || [];
  }
  get step() {
    return this.snapStep || Math.max(1, Math.round(this.view.timing.ppq / 4));
  }
  x(t) {
    return 44 + t / this.view.timing.ppq * 48 * this.zoom;
  }
  selectTrack(id) {
    this.cancel();
    this.scroll = null;
    this.trackId = id;
    this.selected = new Set(this.notes.map((n) => n.id));
    this.render();
  }
  say(message) {
    this.message = message;
    if (this.status) this.status.textContent = message;
  }
  cancel() {
    if (this.gesture) {
      this.gesture.svg.classList.toggle("resizing", false);
      this.gesture.handle?.classList.toggle("active", false);
      this.gesture.svg.removeEventListener("pointermove", this.gesture.move);
      this.gesture.svg.removeEventListener("pointerup", this.gesture.up);
      this.gesture.svg.removeEventListener("pointercancel", this.gesture.cancel);
      this.gesture = null;
    }
  }
  updateHistoryButtons() {
    if (this.undoButton) this.undoButton.disabled = this.pending || !this.undo.length;
    if (this.redoButton) this.redoButton.disabled = this.pending || !this.redo.length;
  }
  async mutate(action, history = true) {
    if (this.pending || !this.view) return;
    const before = this.view.revision;
    const projectId = this.view.projectId;
    const generation = this.generation;
    const focused = this.container.contains(document.activeElement);
    const current = () => this.generation === generation && this.view?.projectId === projectId;
    this.pending = true;
    this.updateHistoryButtons();
    this.say("Saving\u2026");
    try {
      const result = await action(before);
      if (current()) {
        this.ownRevision = result.revision;
        if (history) {
          this.undo.push(before);
          this.redo = [];
        }
      }
      await this.onChange({ projectId, revision: result.revision });
      if (current()) this.say(`Saved revision ${result.revision}`);
      return result;
    } catch (error) {
      if (current()) {
        this.say(error.message);
        if (error.status === 409 || error.code === "REVISION_CONFLICT") {
          this.undo = [];
          this.redo = [];
        }
      }
      this.onError(error);
    } finally {
      this.pending = false;
      this.updateHistoryButtons();
      if (focused && current()) this.container.focus({ preventScroll: true });
    }
  }
  async history(direction) {
    const from = direction === "undo" ? this.undo : this.redo;
    const to = direction === "undo" ? this.redo : this.undo;
    if (!from.length || this.pending || !this.view) return;
    const target = from.at(-1), current = this.view.revision, generation = this.generation;
    const result = await this.mutate((r) => this.api.restore(this.view.projectId, r, target), false);
    if (result && this.generation === generation) {
      from.pop();
      to.push(current);
      this.updateHistoryButtons();
    }
  }
  apply(notes, remove = false) {
    if (!this.selection.length) return this.say("Select notes first.");
    if (this.selection.some((n) => locked(n, this.trackId, this.locks)) || notes.some((n) => locked(n, this.trackId, this.locks))) return this.say("This edit touches protected material. Unlock it first.");
    const end = bounds(notes)?.endTick || 0, total = this.view.timing.totalTicks, bar = this.view.timing.ticksPerBar;
    const extend = end > total ? Math.ceil(end / bar) * bar : void 0;
    if (extend && !this.extend.checked) return this.say(`Edit needs extension to ${extend / bar} bars. Enable \u201CAllow timeline extension\u201D and apply again.`);
    const operations = remove ? this.selection.map((n) => ({ op: "delete", noteId: n.id })) : notes.map((n) => ({ op: "update", noteId: n.id, startTick: n.startTick, durationTicks: n.durationTicks, pitch: n.pitch, velocity: n.velocity }));
    return this.mutate((r) => this.api.editNotes(this.view.projectId, { expectedRevision: r, operations, ...extend ? { extendToTick: extend } : {} }));
  }
  key(e) {
    if (["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(e.target.tagName)) return;
    const mod = e.ctrlKey || e.metaKey;
    if (e.key === "Escape") {
      this.cancel();
      this.draw();
      return;
    }
    if (mod && e.key.toLowerCase() === "a") {
      e.preventDefault();
      this.selected = new Set(this.notes.map((n) => n.id));
      this.draw();
    } else if (mod && e.key.toLowerCase() === "z") {
      e.preventDefault();
      this.history(e.shiftKey ? "redo" : "undo");
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      this.apply([], true);
    } else if (e.key.startsWith("Arrow")) {
      e.preventDefault();
      const dt = e.key === "ArrowRight" ? this.step : e.key === "ArrowLeft" ? -this.step : 0, dp = e.key === "ArrowUp" ? 1 : e.key === "ArrowDown" ? -1 : 0;
      this.apply(e.shiftKey && dt ? resize(this.selection, dt) : move(this.selection, dt, dp));
    }
  }
  render() {
    const scroll = this.scroll ? { x: this.scroll.scrollLeft, y: this.scroll.scrollTop } : null;
    this.container.replaceChildren();
    let tools;
    const group = (title, collapsed = false) => {
      const section = el(collapsed ? "details" : "fieldset", "", { class: "editor-group" });
      section.append(el(collapsed ? "summary" : "legend", title));
      tools = el("div", "", { class: "editor-tools" });
      section.append(tools);
      this.container.append(section);
    };
    group("Track and view");
    const button = (label, fn) => {
      const b = el("button", label, { type: "button", class: "secondary" });
      b.onclick = fn;
      tools.append(b);
      return b;
    };
    const field = (label, value, type = "number") => {
      const l = el("label", label);
      const n = el("input", "", { type, value });
      l.append(n);
      tools.append(l);
      return n;
    };
    const track = el("select", "", { "aria-label": "Edit track" });
    for (const t of this.view.score.tracks) {
      const o = el("option", t.name || t.id, { value: t.id });
      o.selected = t.id === this.trackId;
      track.append(o);
    }
    track.onchange = () => {
      this.trackId = track.value;
      this.scroll = null;
      this.selected.clear();
      this.render();
    };
    tools.append(track);
    button(this.mode === "piano" ? "Show phrase mode" : "Show piano roll", () => {
      this.mode = this.mode === "piano" ? "phrase" : "piano";
      this.render();
    });
    button("Select entire track", () => this.selectTrack(this.trackId));
    this.undoButton = button("Undo", () => this.history("undo"));
    this.redoButton = button("Redo", () => this.history("redo"));
    this.updateHistoryButtons();
    const grid = field("Snap ticks", this.step);
    grid.min = 1;
    grid.onchange = () => {
      this.snapStep = Math.max(1, Math.round(+grid.value) || 1);
      this.draw();
    };
    const zoom = field("Zoom", this.zoom);
    zoom.min = 0.25;
    zoom.max = 8;
    zoom.step = 0.25;
    zoom.onchange = () => {
      this.zoom = Math.max(0.25, Math.min(8, +zoom.value || 1));
      this.draw();
    };
    this.extend = field("Allow timeline extension", "", "checkbox");
    this.extend.checked = this.allowExtension;
    this.extend.onchange = () => {
      this.allowExtension = this.extend.checked;
    };
    if (Object.values(this.track?.automation || {}).some((points) => Array.isArray(points) && points.length)) this.container.append(el("p", "This track has expression/controller curves. Note moves and time stretching leave those curves at their original ticks.", { class: "editor-warning" }));
    group("Selection and transforms");
    if (this.mode === "phrase") {
      const start = field("First bar", 1), end = field("Last bar", Math.ceil(this.view.timing.totalTicks / this.view.timing.ticksPerBar));
      start.min = end.min = 1;
      button("Select passage", () => {
        const a = (+start.value - 1) * this.view.timing.ticksPerBar, b = +end.value * this.view.timing.ticksPerBar;
        if (a < 0 || b <= a) return this.say("Choose a valid bar range.");
        this.selected = new Set(boxSelect(this.notes, a, b).map((n) => n.id));
        this.draw();
      });
      tools.append(el("span", "Passage selection includes every note overlapping these bars.", { class: "hint" }));
    }
    const notePicker = el("select", "", { "aria-label": "Select individual notes", multiple: "", size: 4 });
    for (const n of this.notes) {
      const o = el("option", `${n.id} \xB7 pitch ${n.pitch} \xB7 tick ${n.startTick}`, { value: n.id });
      o.selected = this.selected.has(n.id);
      notePicker.append(o);
    }
    this.notePicker = notePicker;
    notePicker.onchange = () => {
      this.selected = new Set([...notePicker.selectedOptions].map((o) => o.value));
      this.draw();
    };
    tools.append(notePicker);
    const dt = field("Move ticks", 0), dp = field("Move semitones", 0);
    button("Move selection", () => this.apply(move(this.selection, +dt.value || 0, +dp.value || 0)));
    const length = field("Resize by ticks", this.step);
    button("Resize selected lengths", () => this.apply(resize(this.selection, +length.value || 0)));
    const factor = field("Factor", 2);
    factor.min = 0.01;
    factor.step = 0.1;
    const linkedRange = (label, number, min, max, step) => {
      const range = field(label, number.value || number.getAttribute("value"), "range");
      range.min = min;
      range.max = max;
      range.step = step;
      range.oninput = () => { number.value = range.value; };
      number.addEventListener("input", () => {
        range.value = Math.max(min, Math.min(max, +number.value || min));
      });
      return range;
    };
    if (this.mode === "phrase") linkedRange("Time scaling slider", factor, 0.25, 3, 0.05);
    tools.append(el("span", "Length changes keep note starts; Stretch moves starts too.", {class: "hint"}));
    button("Multiply note lengths", () => this.transform(+factor.value, false));
    button("Stretch time and lengths", () => this.transform(+factor.value, true));
    const velocity = field("Velocity", 90);
    velocity.min = 1;
    velocity.max = 127;
    linkedRange("Loudness slider", velocity, 1, 127, 1);
    button("Set velocity", () => this.apply(this.selection.map((n) => ({ ...n, velocity: Math.max(1, Math.min(127, Math.round(+velocity.value) || 1)) }))));
    button("Delete selection", () => this.apply([], true));
    group("Add a note", true);
    const pitch = field("New note pitch", 60), tick = field("New note tick", 0), duration = field("New note length", this.step);
    pitch.min = 0;
    pitch.max = 127;
    tick.min = 0;
    duration.min = 1;
    button("Add note", () => {
      const note = { pitch: Math.max(0, Math.min(127, Math.round(+pitch.value) || 0)), startTick: Math.max(0, snap(+tick.value || 0, this.step)), durationTicks: Math.max(1, Math.round(+duration.value) || 1), velocity: Math.max(1, Math.min(127, Math.round(+velocity.value) || 1)) };
      if (locked(note, this.trackId, this.locks)) return this.say("The new note overlaps protected material.");
      const end = note.startTick + note.durationTicks, bar = this.view.timing.ticksPerBar, extend = end > this.view.timing.totalTicks ? Math.ceil(end / bar) * bar : void 0;
      if (extend && !this.extend.checked) return this.say(`New note needs extension to ${extend / bar} bars. Enable timeline extension and add again.`);
      this.mutate((r) => this.api.editNotes(this.view.projectId, { expectedRevision: r, operations: [{ op: "add", trackId: this.trackId, note }], ...extend ? { extendToTick: extend } : {} }));
    });
    group("Audition and protection");
    button("Preview selection", () => {
      const b = bounds(this.selection);
      if (b) this.onPreview(b);
    });
    button("Loop selected passage", () => {
      const b = bounds(this.selection), bar = this.view.timing.ticksPerBar;
      if (b) this.mutate((r) => this.api.setArrangement(this.view.projectId, { expectedRevision: r, loopEnabled: true, loopStartBar: Math.floor(b.startTick / bar) + 1, loopEndBar: Math.ceil(b.endTick / bar) }));
    });
    button("Protect selection range", () => {
      const b = bounds(this.selection);
      if (b) this.mutate((r) => this.api.lock(this.view.projectId, { expectedRevision: r, trackId: this.trackId, ...b }), false);
    });
    button("Protect entire track", () => this.mutate((r) => this.api.lock(this.view.projectId, { expectedRevision: r, trackId: this.trackId }), false));
    const locks = el("div", "", { class: "editor-locks" });
    for (const l of this.locks.filter((l2) => l2.trackId === this.trackId)) {
      const b = el("button", `Unlock ${l.startTick == null ? "whole track" : `${l.startTick}\u2013${l.endTick} ticks`}`, { type: "button", class: "secondary" });
      b.onclick = () => this.mutate((r) => this.api.unlock(this.view.projectId, l.id, { expectedRevision: r }), false);
      locks.append(b);
    }
    this.container.append(locks);
    this.scroll = el("div", "", { class: "editor-scroll" });
    this.container.append(this.scroll);
    this.status = el("p", "Click a note; Shift-click adds/removes. Drag empty space to select. Drag a note\u2019s right edge to resize the group. Arrow keys move; Shift + left/right resize.", { class: "editor-status", role: "status" });
    this.container.append(this.status);
    group("Refine with your connected agent", true);
    const request = el("input", "", { type: "text", placeholder: "Requested musical refinement", "aria-label": "Requested musical refinement" });
    tools.append(request);
    this.promptBox = el("textarea", "", { class: "editor-prompt", readonly: "", "aria-label": "Exact selection prompt" });
    this.promptBox.hidden = true;
    this.container.append(this.promptBox);
    button("Copy selection for AI", async () => {
      if (!this.selection.length) return this.say("Select notes first.");
      this.promptBox.hidden = false;
      this.promptBox.value = prompt(this.view, this.trackId, this.selection, request.value);
      const result = await copyText(this.promptBox.value, this.promptBox);
      this.say(`${result === "copied" ? "Copied." : "Select and copy the prompt."} Paste into your connected agent to request the edit.`);
    });
    this.draw();
    if (scroll) {
      this.scroll.scrollLeft = scroll.x;
      this.scroll.scrollTop = scroll.y;
    } else {
      const pitches = this.notes.map((n) => n.pitch);
      const center = pitches.length ? (Math.min(...pitches) + Math.max(...pitches)) / 2 : 60;
      this.scroll.scrollTop = Math.max(0, 24 + (127 - center) * 14 - (this.scroll.clientHeight || 400) / 2);
    }
  }
  transform(factor, stretch) {
    try {
      this.apply(scale(this.selection, factor, stretch));
    } catch (e) {
      this.say(e.message);
    }
  }
  draw(preview = null, box = null) {
    if (!this.scroll) return;
    if (this.notePicker) for (const o of this.notePicker.options) o.selected = this.selected.has(o.value);
    const width = this.x(this.view.timing.totalTicks) + 40, height = 128 * 14 + 24;
    const s = svg("svg", { class: "editor-roll", width, height, role: "img", "aria-label": "Piano roll: tick time horizontally, MIDI pitch vertically" });
    const ruler = svg("svg", { class: "editor-ruler", width, height: 24, role: "img", "aria-label": "Time ruler: click a bar to seek" });
    ruler.onclick = (event) => {
      const localX = event.clientX - ruler.getBoundingClientRect().left;
      const tick = snap((localX - 44) / (48 * this.zoom) * this.view.timing.ppq, this.step);
      this.onSeek(Math.max(0, Math.min(this.view.timing.totalTicks, tick)));
    };
    this.scroll.replaceChildren(ruler, s);
    for (let p = 0; p < 128; p++) {
      const y = 24 + (127 - p) * 14;
      s.append(svg("line", { class: "grid", x1: 44, x2: width, y1: y, y2: y }));
      if (p % 12 === 0) {
        const t = svg("text", { x: 2, y: y + 11 });
        t.textContent = `C${p / 12 - 1}`;
        s.append(t);
      }
    }
    const bar = this.view.timing.ticksPerBar;
    // Keep dense grids bounded on long arrangements while snap math remains exact.
    const visibleStep = this.step * Math.max(1, Math.ceil(this.view.timing.totalTicks / this.step / 4000));
    for (let tick = 0; tick < this.view.timing.totalTicks; tick += visibleStep) {
      if (tick % bar) s.append(svg("line", { class: "grid snap-line", x1: this.x(tick), x2: this.x(tick), y1: 24, y2: height }));
    }
    for (let t = 0; t <= this.view.timing.totalTicks; t += bar) {
      s.append(svg("line", { class: "grid", x1: this.x(t), x2: this.x(t), y1: 0, y2: height }));
      const label = svg("text", { x: this.x(t) + 3, y: 14 });
      label.textContent = 1 + t / bar;
      s.append(label);
      const rulerLabel = svg("text", { x: this.x(t) + 3, y: 14 });
      rulerLabel.textContent = `Bar ${1 + t / bar}`;
      ruler.append(rulerLabel, svg("line", {x1:this.x(t), x2:this.x(t), y1:16, y2:24}));
    }
    for (const l of this.locks.filter((l2) => l2.trackId === this.trackId)) s.append(svg("rect", { class: "protection", x: this.x(l.startTick || 0), y: 24, width: this.x(l.endTick ?? this.view.timing.totalTicks) - this.x(l.startTick || 0), height: height - 24 }));
    const altered = new Map((preview || []).map((n) => [n.id, n]));
    this.noteRects = new Map();
    this.resizeHandles = new Map();
    for (const original of this.notes) {
      const n = altered.get(original.id) || original;
      const r = svg("rect", { class: `editor-note${this.selected.has(n.id) ? " selected" : ""}${locked(n, this.trackId, this.locks) ? " protected" : ""}`, x: this.x(n.startTick), y: 24 + (127 - n.pitch) * 14, width: Math.max(3, this.x(n.durationTicks) - 44), height: 13, rx: 2, "data-note": n.id });
      this.noteRects.set(n.id, r);
      const title = svg("title", {});
      title.textContent = `${n.id}: pitch ${n.pitch}, tick ${n.startTick}, length ${n.durationTicks}, velocity ${n.velocity}`;
      r.append(title);
      s.append(r);
      if (!locked(n, this.trackId, this.locks)) {
        const width = Math.max(3, this.x(n.durationTicks) - 44), grip = Math.min(7, width);
        const handle = svg("rect", { class: "editor-resize-handle", x: this.x(n.startTick) + width - grip, y: 24 + (127 - n.pitch) * 14, width: grip, height: 13, rx: 2, "data-resize-note": n.id });
        const hint = svg("title", {});
        hint.textContent = "Drag to resize; snaps the note end to the grid.";
        handle.append(hint);
        this.resizeHandles.set(n.id, handle);
        s.append(handle);
      }
    }
    if (box) s.append(svg("rect", { class: "marquee", x: Math.min(box.a.x, box.b.x), y: Math.min(box.a.y, box.b.y), width: Math.abs(box.a.x - box.b.x), height: Math.abs(box.a.y - box.b.y) }));
    this.cursor = svg("line", { class: "cursor", x1: this.x(this.position), x2: this.x(this.position), y1: 0, y2: height });
    s.append(this.cursor);
    s.onpointerdown = (e) => this.pointer(e, s);
    this.status.textContent = this.message || `${this.selected.size} notes selected. Click or Shift-click notes; drag empty space to select. Arrow keys move; Shift + left/right resize.`;
  }
  pointer(e, s) {
    if (this.pending || e.button !== 0) return;
    e.preventDefault();
    this.container.focus();
    const point = (ev) => {
      const r = s.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    };
    const a = point(e), handleId = e.target.getAttribute("data-resize-note"), id = handleId || e.target.getAttribute("data-note");
    if (a.y < 24) {
      this.onSeek(Math.max(0, snap((a.x - 44) / (48 * this.zoom) * this.view.timing.ppq, this.step)));
      return;
    }
    if (id) {
      if (e.shiftKey) {
        if (this.selected.has(id)) this.selected.delete(id);
        else this.selected.add(id);
        this.draw();
        return;
      }
      if (!this.selected.has(id)) this.selected = /* @__PURE__ */ new Set([id]);
    }
    const originals = this.selection, initial = new Set(this.selected), n = this.notes.find((n2) => n2.id === id);
    const resizing = !!handleId;
    if (id && originals.some((n2) => locked(n2, this.trackId, this.locks))) {
      this.draw();
      this.say("Protected notes cannot be dragged. Unlock first.");
      return;
    }
    let result = null, moved = false;
    const handle = resizing ? this.resizeHandles.get(id) : null;
    s.classList.toggle("resizing", resizing);
    handle?.classList.toggle("active", true);
    s.setPointerCapture(e.pointerId);
    const marquee = svg("rect", { class: "marquee", x: a.x, y: a.y, width: 0, height: 0 });
    s.append(marquee);
    const motion = (ev) => {
      const b = point(ev);
      moved ||= Math.abs(b.x - a.x) + Math.abs(b.y - a.y) > 3;
      if (!moved) return;
      if (id) {
        const raw = (b.x - a.x) / (48 * this.zoom) * this.view.timing.ppq;
        const dt = resizing ? snap(n.startTick + n.durationTicks + raw, this.step) - n.startTick - n.durationTicks : snap(raw, this.step);
        result = resizing ? resize(originals, dt) : move(originals, dt, Math.round((a.y - b.y) / 14));
        this.previewGeometry(result);
      } else {
        for (const [key, value] of Object.entries({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) })) marquee.setAttribute(key, value);
        const lo = Math.max(0, (Math.min(a.x, b.x) - 44) / (48 * this.zoom) * this.view.timing.ppq), hi = Math.max(lo + 1, (Math.max(a.x, b.x) - 44) / (48 * this.zoom) * this.view.timing.ppq);
        const notes = boxSelect(this.notes, lo, hi, 127 - Math.floor((Math.max(a.y, b.y) - 24) / 14), 127 - Math.floor((Math.min(a.y, b.y) - 24) / 14));
        this.selected = /* @__PURE__ */ new Set([...e.shiftKey ? initial : [], ...notes.map((n2) => n2.id)]);
        s.querySelectorAll(".editor-note").forEach((r) => r.classList.toggle("selected", this.selected.has(r.getAttribute("data-note"))));
      }
    };
    const up = () => {
      this.cancel();
      if (!id && !moved) this.selected.clear();
      this.message = "";
      this.draw();
      if (result) this.apply(result);
    };
    const cancel = () => {
      this.cancel();
      this.draw();
    };
    this.gesture = { svg: s, handle, move: motion, up, cancel };
    s.addEventListener("pointermove", motion);
    s.addEventListener("pointerup", up);
    s.addEventListener("pointercancel", cancel);
  }
  previewGeometry(notes) {
    for (const n of notes) {
      const r = this.noteRects.get(n.id);
      if (r) {
        r.setAttribute("x", this.x(n.startTick));
        r.setAttribute("y", 24 + (127 - n.pitch) * 14);
        r.setAttribute("width", Math.max(3, this.x(n.durationTicks) - 44));
        const handle = this.resizeHandles.get(n.id);
        if (handle) {
          const width = Math.max(3, this.x(n.durationTicks) - 44), grip = Math.min(7, width);
          handle.setAttribute("x", this.x(n.startTick) + width - grip);
          handle.setAttribute("y", 24 + (127 - n.pitch) * 14);
          handle.setAttribute("width", grip);
        }
      }
    }
  }
}
