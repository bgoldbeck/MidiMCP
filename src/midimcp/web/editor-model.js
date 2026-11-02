// Pure editor geometry. All ranges are half open; tick zero is valid.
export const overlaps = (a, b, c, d) => a < d && c < b;
export const snap = (tick, step) => Math.round(tick / step) * step;
export function bounds(notes) {
  return notes.length ? { startTick: Math.min(...notes.map(n => n.startTick)), endTick: Math.max(...notes.map(n => n.startTick + n.durationTicks)) } : null;
}
export function locked(note, trackId, locks) {
  return locks.some(l => l.trackId === trackId && (l.startTick == null || overlaps(note.startTick, note.startTick + note.durationTicks, l.startTick, l.endTick)));
}
export function move(notes, dt, dp) {
  if (!Number.isFinite(dt) || !Number.isFinite(dp)) throw new Error('Movement must be finite.');
  if (!notes.length) return [];
  dt = Math.max(Math.round(dt), -Math.min(...notes.map(n => n.startTick)));
  dp = Math.max(-Math.min(...notes.map(n => n.pitch)), Math.min(Math.round(dp), 127 - Math.max(...notes.map(n => n.pitch))));
  return notes.map(n => ({ ...n, startTick: n.startTick + dt, pitch: n.pitch + dp }));
}
export function resize(notes, delta) {
  if (!Number.isFinite(delta)) throw new Error('Resize amount must be finite.');
  if (!notes.length) return [];
  delta = Math.max(Math.round(delta), 1 - Math.min(...notes.map(n => n.durationTicks)));
  return notes.map(n => ({ ...n, durationTicks: n.durationTicks + delta }));
}
export function scale(notes, factor, stretch = false) {
  if (!(factor > 0) || !Number.isFinite(factor)) throw new Error('Factor must be positive.');
  const anchor = bounds(notes)?.startTick || 0;
  return notes.map(n => ({ ...n, startTick: stretch ? anchor + Math.round((n.startTick - anchor) * factor) : n.startTick, durationTicks: Math.max(1, Math.round(n.durationTicks * factor)) }));
}
export function boxSelect(notes, start, end, low = 0, high = 127) {
  return notes.filter(n => n.pitch >= low && n.pitch <= high && overlaps(n.startTick, n.startTick + n.durationTicks, start, end));
}
export function prompt(view, trackId, notes, request) {
  const range = bounds(notes);
  return `Refine this exact MidiMCP selection. Project: ${view.projectId}; expected revision: ${view.revision}; track: ${trackId}.\nSelection bounds (half-open ticks): ${range ? `[${range.startTick}, ${range.endTick})` : 'empty'}.\nRequest: ${request || 'Suggest a musical refinement before editing.'}\nNotes (exact ticks):\n${JSON.stringify(notes.map(({ id, startTick, durationTicks, pitch, velocity }) => ({ id, startTick, durationTicks, pitch, velocity })), null, 2)}\nPreserve unselected notes and all protection locks. Read the current revision before editing; if it differs, ask me to reselect.`;
}
