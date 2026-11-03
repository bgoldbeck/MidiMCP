// Real-browser integration against a seeded local test server. No production songs.
// Usage: node web-tests/e2e-editor.mjs <baseUrl> <token> [screenshotPath]
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");
const [base, token, screenshot] = process.argv.slice(2);
const pid = "browser-test-song";
const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
async function api(method, path, body) {
  const response = await fetch(base + path, { method, headers, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  assert.equal(response.ok, true, JSON.stringify(data));
  return data;
}
const read = () => api("GET", `/api/projects/${pid}`);
let baseline = await read();
for (const lock of baseline.brief.locks) {
  await api("DELETE", `/api/projects/${pid}/locks/${lock.id}`, { expectedRevision: baseline.revision });
  baseline = await read();
}
if (baseline.revision !== 3) {
  await api("POST", `/api/projects/${pid}/restore`, { expectedRevision: baseline.revision, revision: 3 });
}
baseline = await read();
const browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}), headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
page.on("dialog", dialog => dialog.accept());
const button = name => page.getByRole("button", { name, exact: true });
async function waitRevision(after) {
  await page.waitForFunction(r => Number(document.getElementById("revision").textContent.replace(/\D/g, "")) > r, after);
  await page.waitForFunction(() => !document.querySelector(".editor-status")?.textContent.includes("Saving"));
  return read();
}
try {
  await page.addInitScript(t => localStorage.setItem("midimcp.token", t), token);
  await page.goto(`${base}/ui/#${pid}`);
  await page.waitForFunction(() => document.getElementById("player-state").textContent === "ready", null, { timeout: 60000 });
  await button("Edit notes in Flute").click();
  await page.locator(".editor-note").first().waitFor();
  assert.equal(await page.locator(".editor-note").count(), 12);
  let state = await read();
  const ids = state.score.tracks[0].notes.slice(0, 2).map(n => n.id);
  // Exercise real pointer capture, Shift selection, movement and group edge resize.
  await page.getByLabel("Select individual notes").selectOption([ids[0]]);
  const firstNote = page.locator(`[data-note="${ids[0]}"]`);
  const secondNote = page.locator(`[data-note="${ids[1]}"]`);
  await secondNote.click({ modifiers: ["Shift"] });
  assert.equal(await page.locator(".editor-note.selected").count(), 2);
  await firstNote.scrollIntoViewIfNeeded();
  let box = await firstNote.boundingBox();
  await page.mouse.move(box.x + 10, box.y + 6);
  await page.mouse.down();
  await page.mouse.move(box.x + 22, box.y - 8, { steps: 4 });
  await page.mouse.up();
  let gesture = await waitRevision(state.revision);
  assert.deepEqual(gesture.score.tracks[0].notes.slice(0, 2).map(n => [n.startTick, n.pitch]), [[240, 63], [1200, 65]]);
  await button("Undo").click();
  state = await waitRevision(gesture.revision);
  await firstNote.scrollIntoViewIfNeeded();
  box = await firstNote.boundingBox();
  const handle = page.locator(`[data-resize-note="${ids[0]}"]`);
  await page.mouse.move(box.x + box.width - 2, box.y + 6);
  assert.equal(await handle.evaluate(el => getComputedStyle(el).cursor), "ew-resize");
  assert.equal(await handle.evaluate(el => getComputedStyle(el).fillOpacity), "1");
  await page.mouse.down();
  await page.mouse.move(box.x + box.width + 10, box.y + 6, { steps: 4 });
  await page.mouse.up();
  gesture = await waitRevision(state.revision);
  assert.deepEqual(gesture.score.tracks[0].notes.slice(0, 2).map(n => n.durationTicks), [1200, 1200]);
  await button("Undo").click();
  state = await waitRevision(gesture.revision);

  // Marquee selects by both pitch and time, without creating a revision.
  await firstNote.scrollIntoViewIfNeeded();
  const a = await firstNote.boundingBox(), b = await secondNote.boundingBox();
  await page.mouse.move(a.x - 3, Math.min(a.y, b.y) - 3);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width + 3, Math.max(a.y, b.y) + 16, { steps: 4 });
  await page.mouse.up();
  assert.equal(await page.locator(".editor-note.selected").count(), 2);
  assert.equal((await read()).revision, state.revision);
  await page.getByLabel("Select individual notes").selectOption(ids);
  await page.getByLabel("Move ticks", { exact: true }).fill("240");
  await button("Move selection").click();
  let changed = await waitRevision(state.revision);
  assert.deepEqual(changed.score.tracks[0].notes.slice(0, 2).map(n => n.startTick), [240, 1200]);
  assert.deepEqual(changed.score.tracks[0].notes.slice(2), baseline.score.tracks[0].notes.slice(2));
  await button("Undo").click();
  state = await waitRevision(changed.revision);
  assert.deepEqual(state.score.tracks[0].notes, baseline.score.tracks[0].notes);
  await button("Redo").click();
  changed = await waitRevision(state.revision);
  assert.equal(changed.score.tracks[0].notes[0].startTick, 240);

  await page.getByLabel("Select individual notes").selectOption(ids);
  await page.getByLabel("Velocity", { exact: true }).fill("67");
  await button("Set velocity").click();
  state = await waitRevision(changed.revision);
  assert.ok(state.score.tracks[0].notes.filter(n => ids.includes(n.id)).every(n => n.velocity === 67));
  await page.getByText("Refine with your connected agent", { exact: true }).click();
  await button("Copy selection for AI").click();
  const prompt = await page.getByLabel("Exact selection prompt").inputValue();
  assert.ok(prompt.includes(pid) && ids.every(id => prompt.includes(id)));

  await button("Protect selection range").click();
  changed = await waitRevision(state.revision);
  assert.equal(changed.brief.locks.length, 1);
  const beforeProtected = changed.revision;
  await button("Move selection").click();
  await page.waitForTimeout(150);
  assert.equal((await read()).revision, beforeProtected);
  await page.getByRole("button", { name: /^Unlock / }).click();
  state = await waitRevision(beforeProtected);
  assert.equal(state.brief.locks.length, 0);

  await button("Show phrase mode").click();
  await page.getByLabel("First bar", { exact: true }).fill("2");
  await page.getByLabel("Last bar", { exact: true }).fill("2");
  await button("Select passage").click();
  assert.ok(await page.locator(".editor-note.selected").count() > 0);
  await button("Preview selection").click();
  await page.locator("#selection-preview:not([hidden])").waitFor();
  assert.equal((await read()).revision, state.revision);
  await button("Return to whole song").click();
  await page.locator("#selection-preview[hidden]").waitFor({ state: "attached" });
  await button("Loop selected passage").click();
  changed = await waitRevision(state.revision);
  assert.equal(changed.score.timeline.loop.enabled, true);
  await page.waitForFunction(() => document.getElementById("loop").checked);

  await button("Show piano roll").click();
  await button("Select entire track").click();
  await page.getByLabel("Factor", { exact: true }).fill("2");
  await page.getByLabel("Allow timeline extension", { exact: true }).check();
  await button("Stretch time and lengths").click();
  state = await waitRevision(changed.revision);
  assert.ok(state.timing.totalTicks > baseline.timing.totalTicks);
  await page.reload();
  await page.waitForFunction(r => document.getElementById("revision").textContent.includes(String(r)), state.revision);
  assert.equal((await read()).score.tracks[0].notes[1].startTick, state.score.tracks[0].notes[1].startTick);
  await button("Edit notes in Flute").click();
  if (screenshot) await page.screenshot({ path: screenshot, fullPage: true });

  // Failed navigation must not leave the currently displayed song stale.
  await page.route("**/api/projects/evil-title", route => route.fulfill({
    status: 503, contentType: "application/json", body: JSON.stringify({ code: "TEST_FAILURE", message: "Test navigation unavailable" }),
  }));
  await page.locator('#project-list li[data-project="evil-title"]').click();
  await page.waitForFunction(() => document.getElementById("toast-text").textContent.includes("Test navigation unavailable"));
  await page.unroute("**/api/projects/evil-title");
  await page.getByLabel("Select individual notes").selectOption(ids);
  await page.getByLabel("Velocity", { exact: true }).fill("69");
  await button("Set velocity").click();
  state = await waitRevision(state.revision);
  assert.equal(state.score.tracks[0].notes[0].velocity, 69);

  // A completed save must not cancel navigation that started before its reply.
  let finishSave, finishNavigation, navigationStarted;
  const saveReady = new Promise(resolve => { finishSave = resolve; });
  const navigationReady = new Promise(resolve => { finishNavigation = resolve; });
  const navigationSeen = new Promise(resolve => { navigationStarted = resolve; });
  await page.route(`**/api/projects/${pid}/notes`, async route => {
    const response = await route.fetch();
    await saveReady;
    await route.fulfill({ response });
  });
  await page.route("**/api/projects/evil-title", async route => {
    const response = await route.fetch();
    navigationStarted();
    await navigationReady;
    await route.fulfill({ response });
  });
  await page.getByLabel("Select individual notes").selectOption(ids);
  await page.getByLabel("Velocity", { exact: true }).fill("68");
  await button("Set velocity").click();
  await page.locator('#project-list li[data-project="evil-title"]').click();
  await navigationSeen;
  finishSave();
  await page.waitForTimeout(200);
  finishNavigation();
  await page.waitForFunction(() => document.getElementById("song-title").textContent.includes("Evil Title"));
  assert.deepEqual(errors, []);
  console.log(`EDITOR E2E PASSED: move, undo/redo, velocity, AI prompt, locks, phrase selection, exact preview, saved loop, stretch, reload (revision ${state.revision})`);
} finally {
  await browser.close();
}
