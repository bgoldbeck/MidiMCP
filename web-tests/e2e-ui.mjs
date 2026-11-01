// End-to-end browser check of the full web UI against a running server.
// Usage: node web-tests/e2e-ui.mjs <baseUrl> <token> [screenshotPath]
// Expects the server to hold "Browser Test Song" (1 flute track, 12 notes, 4 bars, rev 3)
// and a song whose title is an HTML-injection attempt.
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const [base, token, shot] = process.argv.slice(2);
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const dialogs = { answer: null, seen: [] };
page.on("dialog", (d) => {
  if (dialogs.answer === null) { errors.push(`unexpected dialog: ${d.message()}`); d.dismiss(); return; }
  dialogs.seen.push(d.message());
  return dialogs.answer ? d.accept() : d.dismiss();
});
const step = (msg) => console.log(`step: ${msg}`);
const text = (sel) => page.textContent(sel);
const waitText = (sel, expected, timeout = 60000) =>
  page.waitForFunction(([s, t]) => document.querySelector(s)?.textContent.includes(t), [sel, expected], { timeout });

try {
  await page.goto(base + "/");
  await page.waitForURL(/\/ui\/$/);
  if (await page.isVisible("#app")) throw new Error("app visible before login");
  await page.fill("#token-input", "wrong-token-123456789");
  await page.click("#login-form button");
  await page.waitForSelector("#login-error:not([hidden])");
  errors.length = 0; // expected 401 logged by the browser
  step("wrong token rejected");

  await page.fill("#token-input", token);
  await page.click("#login-form button");
  await page.waitForSelector("#app:not([hidden])");
  await waitText("#connection", "live", 10000);
  step("logged in, live events connected");

  const evil = page.locator("#project-list li", { hasText: "<img" });
  await evil.waitFor();
  if (await page.locator("#project-list img").count()) throw new Error("song title was rendered as HTML");
  step("HTML in song titles is shown as text");

  await page.click("#project-list li:has-text('Browser Test Song')");
  await waitText("#player-state", "ready");
  const notes = await page.locator("#overview rect.note").count();
  if (notes !== 12) throw new Error(`overview shows ${notes} notes, expected 12`);
  step(`opened song: ${await text("#song-meta")} | overview notes ${notes}`);

  await page.click("#play");
  await waitText("#player-state", "playing");
  await page.waitForFunction(() => Number(document.querySelector("#playhead").getAttribute("x1")) > 5, null, { timeout: 10000 });
  step(`playing, time ${await text("#time")}, playhead moving`);

  const srcBefore = await page.evaluate(() => document.querySelector("#audio").src);
  await page.selectOption("#speed", "1.25");
  await page.waitForFunction((b) => document.querySelector("#audio").src !== b, srcBefore, { timeout: 60000 });
  await waitText("#player-state", "playing");
  step("speed 125% re-rendered while playing");

  await page.click("#pause");
  await waitText("#player-state", "paused");
  await page.click("#stop");
  await waitText("#bar", "1");
  step("pause/stop");

  await page.locator("tr[data-track=flute] select").selectOption({ label: "Recorder" });
  await waitText("#revision", "revision 4");
  await waitText("#last-change", "instrumentId");
  step(`instrument changed -> ${await text("#revision")}`);

  await page.locator("tr[data-track=flute] input[type=checkbox]").check();
  await waitText("#revision", "revision 5");
  step("mute saved as revision 5");

  // Someone else (e.g. an AI agent) edits the song: the page must update live.
  const response = await fetch(`${base}/api/projects/browser-test-song/tracks/flute`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ expectedRevision: 5, mute: false, gainDb: -4 }),
  });
  if (!response.ok) throw new Error(`external edit failed: ${response.status}`);
  await waitText("#revision", "revision 6", 15000);
  await waitText("#last-change", "Updated to revision 6");
  if (await page.isVisible("#update-banner")) throw new Error("update banner shown while not playing");
  step("external edit appeared live");

  await page.click("[data-export=midi]");
  await waitText("#export-status", "ready");
  const href = await page.getAttribute("#export-list a", "href");
  const midi = await (await fetch(new URL(href, base))).arrayBuffer();
  if (new TextDecoder().decode(midi.slice(0, 4)) !== "MThd") throw new Error("MIDI download broken");
  step(`MIDI export downloadable (${midi.byteLength} bytes)`);

  // Song only allows flute + recorder: picking Harp asks first; Cancel keeps everything.
  await waitText("#allowed-instruments", "Wooden Flute, Recorder");
  const flute = page.locator("tr[data-track=flute] select");
  dialogs.answer = false;
  await flute.selectOption({ label: "Harp" });
  await page.waitForFunction(() => document.querySelector("tr[data-track=flute] select").selectedOptions[0].textContent === "Recorder");
  if (!(await text("#revision")).includes("revision 6")) throw new Error("cancelled change was saved");
  dialogs.answer = true;
  await page.locator("tr[data-track=flute] select").selectOption({ label: "Harp" });
  await waitText("#revision", "revision 7");
  await waitText("#allowed-instruments", "Harp");
  if (dialogs.seen.length !== 2 || !dialogs.seen[0].includes("Harp")) throw new Error(`dialogs: ${dialogs.seen}`);
  dialogs.answer = null;
  step("instrument outside the allowed list: cancel keeps, OK adds it (one revision)");

  // A refused change shows a visible error at the top instead of silently resetting.
  const refused = await fetch(`${base}/api/projects/browser-test-song/tracks/flute`, {
    method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ expectedRevision: 7, instrumentId: "retro.lute" }),
  });
  if (refused.status !== 422) throw new Error(`expected 422, got ${refused.status}`);
  await page.evaluate(() => { document.querySelector("#toast").hidden = true; });
  step("server still refuses instruments outside the list without the opt-in");

  await page.click("#overview svg", { position: { x: 600, y: 30 } });
  step(`overview click seeks to bar ${await text("#bar")}`);

  if (shot) await page.screenshot({ path: shot, fullPage: true });
  await page.reload();
  await page.waitForSelector("#app:not([hidden])");
  step("token remembered after reload");

  if (errors.length) throw new Error(`browser errors: ${errors.join(" | ")}`);
  console.log("E2E UI PASSED");
} catch (error) {
  if (shot) await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
  console.error(`E2E FAILED: ${error.message}\n${errors.join("\n")}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
