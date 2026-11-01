// End-to-end browser check of the full web UI against a running server.
// Usage: node web-tests/e2e-ui.mjs <baseUrl> <token> [screenshotPath]
// Expects the server to hold "Browser Test Song" (1 flute track, 12 notes, 4 bars, rev 3)
// and a song whose title is an HTML-injection attempt.
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const [base, token, shot] = process.argv.slice(2);
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const dialogs = { answer: null, seen: [], promptText: "" };
page.on("dialog", (d) => {
  if (dialogs.answer === null) { errors.push(`unexpected dialog: ${d.message()}`); d.dismiss(); return; }
  dialogs.seen.push(d.message());
  if (!dialogs.answer) return d.dismiss();
  return d.type() === "prompt" ? d.accept(dialogs.promptText) : d.accept();
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

  // Changing an instrument while playing re-renders and keeps playing from the same spot.
  await page.click("#play");
  await waitText("#player-state", "playing");
  await page.locator("tr[data-track=flute] select").selectOption({ label: "Recorder" });
  await waitText("#revision", "revision 4");
  await waitText("#last-change", "instrumentId");
  await waitText("#player-state", "playing", 60000);
  step(`instrument changed while playing -> ${await text("#revision")}, playback resumed`);
  await page.click("#pause");
  await waitText("#player-state", "paused");

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

  // Download card: each button saves the file straight to the computer.
  const [midiDownload] = await Promise.all([page.waitForEvent("download"), page.click("[data-export=midi]")]);
  const midi = await readFile(await midiDownload.path());
  if (midi.subarray(0, 4).toString("latin1") !== "MThd") throw new Error("MIDI download broken");
  if (!midiDownload.suggestedFilename().endsWith(".mid")) throw new Error(`MIDI file named ${midiDownload.suggestedFilename()}`);
  await waitText("#export-status", "downloaded:");
  await waitText("#export-list", ".mid");
  step(`MIDI downloaded in the browser (${midi.byteLength} bytes)`);

  await page.selectOption("#mp3-bitrate", "128");
  const [mp3Download] = await Promise.all([page.waitForEvent("download"), page.click("[data-export=mp3]")]);
  const mp3 = await readFile(await mp3Download.path());
  if (mp3.subarray(0, 3).toString("latin1") !== "ID3") throw new Error("MP3 download broken");
  if (!mp3Download.suggestedFilename().endsWith("-128k.mp3")) throw new Error(`MP3 named ${mp3Download.suggestedFilename()}`);
  step(`MP3 (128 kbps) downloaded in the browser (${mp3.byteLength} bytes)`);

  // Header "Download song" button: one click, chosen format, remembered after reload.
  await page.selectOption("#download-format", "mp3:320");
  const [songDownload] = await Promise.all([page.waitForEvent("download"), page.click("#download-song")]);
  if (!songDownload.suggestedFilename().endsWith("-320k.mp3")) throw new Error(`song named ${songDownload.suggestedFilename()}`);
  await waitText("#download-status", "downloaded:");
  const listed = await page.locator("#export-list a.download-link").count();
  if (listed < 3 || await page.isHidden("#export-list-title")) throw new Error(`earlier downloads list shows ${listed}`);
  step(`Download song button saved ${songDownload.suggestedFilename()}; ${listed} earlier downloads listed`);

  // Ready-made Antigravity config: download it and connect with exactly what it says.
  const [configDownload] = await Promise.all([page.waitForEvent("download"), page.click("#config-antigravity")]);
  if (configDownload.suggestedFilename() !== "mcp_config.json") throw new Error(`config named ${configDownload.suggestedFilename()}`);
  const config = JSON.parse(await readFile(await configDownload.path(), "utf8")).mcpServers.midimcp;
  if (config.serverUrl !== `${base}/mcp`) throw new Error(`serverUrl ${config.serverUrl}`);
  const handshake = await fetch(config.serverUrl, {
    method: "POST",
    headers: { ...config.headers, "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "e2e", version: "1" } } }),
  });
  const reply = await handshake.text();
  if (handshake.status !== 200 || !reply.includes('"midimcp"')) throw new Error(`MCP handshake ${handshake.status}: ${reply.slice(0, 200)}`);
  const [toolsDownload] = await Promise.all([page.waitForEvent("download"), page.click("#config-tools")]);
  const toolList = JSON.parse(await readFile(await toolsDownload.path(), "utf8"));
  if (!toolList.tools.some((t) => t.name === "replace_notes" && t.inputSchema)) throw new Error("tool schema download broken");
  step(`Antigravity config downloaded and connects; tool list has ${toolList.tools.length} tools with schemas`);

  // Favorites and collections: star, make a collection, file the song, rename, filter, delete.
  const songRow = "#project-list li[data-project=browser-test-song]";
  await page.click("#favorite-song");
  await waitText("#favorite-song", "★");
  await waitText(`${songRow} .star`, "★");
  await waitText("#library-filters [data-filter=favorites]", "1");
  dialogs.answer = true;
  dialogs.promptText = "Town themes";
  await page.click("#new-collection");
  await waitText("#library-filters .chip.active", "Town themes");
  await waitText("#library-empty", "No songs in this collection yet");
  await page.click("#song-collections summary");
  await page.check("#song-collections-list input[data-collection=town-themes]");
  await waitText("#song-collections-label", "Town themes");
  await page.waitForSelector(`${songRow} .badge`);
  if (await page.locator("#project-list li").count() !== 1) throw new Error("collection filter shows other songs");
  dialogs.promptText = "Towns";
  await page.click("#rename-collection");
  await waitText("#library-filters .chip.active", "Towns");
  await waitText("#song-collections-label", "Towns");
  await page.click("#library-filters [data-filter=favorites]");
  if (await page.locator("#project-list li").count() !== 1) throw new Error("favorites filter is wrong");
  await page.click("#library-filters [data-filter=all]");
  await page.waitForFunction(() => document.querySelectorAll("#project-list li").length === 2);
  await page.selectOption("#library-sort", "title");
  const firstTitle = await page.locator("#project-list li .title").first().textContent();
  if (firstTitle !== "Browser Test Song") throw new Error(`title sort put ${firstTitle} first`);
  await page.click("#library-filters [data-filter=town-themes]");
  await page.click("#delete-collection");
  await waitText("#library-filters .chip.active", "All songs");
  await waitText("#song-collections-label", "none");
  if (dialogs.seen.length !== 3) throw new Error(`collection dialogs: ${dialogs.seen}`);
  dialogs.answer = null;
  dialogs.seen = [];
  if (await page.locator("#library-filters [data-filter=town-themes]").count()) throw new Error("collection not deleted");
  await page.click("#favorite-song");
  await waitText("#favorite-song", "☆");
  step("favorites + collections: star, new collection, file song, rename, filter, sort, delete");

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

  // Reset to default: the seed song started with a wooden flute.
  await page.click("tr[data-track=flute] button[data-reset=instrument]");
  await waitText("#revision", "revision 8");
  await page.waitForFunction(() => document.querySelector("tr[data-track=flute] select").selectedOptions[0].textContent === "Wooden Flute");
  if (await page.locator("tr[data-track=flute] button[data-reset=instrument]").count()) throw new Error("reset button still shown");
  step("instrument reset to its default (Wooden Flute)");

  // A refused change shows a visible error at the top instead of silently resetting.
  const refused = await fetch(`${base}/api/projects/browser-test-song/tracks/flute`, {
    method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ expectedRevision: 8, instrumentId: "retro.lute" }),
  });
  if (refused.status !== 422) throw new Error(`expected 422, got ${refused.status}`);
  await page.evaluate(() => { document.querySelector("#toast").hidden = true; });
  step("server still refuses instruments outside the list without the opt-in");

  await page.click("#overview svg", { position: { x: 600, y: 30 } });
  step(`overview click seeks to bar ${await text("#bar")}`);

  // Delete: Cancel keeps the song, OK removes it from the library (moved to trash).
  dialogs.answer = false;
  dialogs.seen.length = 0;
  await page.click("#delete-song");
  if (!(await page.isVisible("#song"))) throw new Error("cancelled delete closed the song");
  dialogs.answer = true;
  await page.click("#delete-song");
  await page.waitForSelector("#welcome-note:not([hidden])");
  await page.waitForFunction(() => ![...document.querySelectorAll("#project-list li")].some((li) => li.textContent.includes("Browser Test Song")));
  if (dialogs.seen.length !== 2 || !dialogs.seen[0].includes("trash")) throw new Error(`delete dialogs: ${dialogs.seen}`);
  dialogs.answer = null;
  step(`delete: cancel keeps, OK removes -> ${await text("#welcome-note")}`);

  // Templates page: view a built-in, duplicate it, edit the copy's JSON, delete it.
  await page.click("#tabs .tab[data-view=templates]");
  await page.click("#template-list li:has-text('Peaceful Town')");
  await waitText("#template-detail", "G  Em  C  D");
  // Copy prompt must work on plain-HTTP LAN addresses, where navigator.clipboard is missing.
  await page.evaluate(() => {
    Object.defineProperty(window, "isSecureContext", { value: false });
    Object.defineProperty(Navigator.prototype, "clipboard", { get: () => undefined });
    document.addEventListener("copy", () => { window.copiedText = document.activeElement.value; });
  });
  await page.click("#template-detail button:has-text('Copy prompt')");
  await waitText("#template-detail", "Copied");
  const copied = await page.evaluate(() => window.copiedText || "");
  if (!copied.includes('"peaceful-town" template')) throw new Error(`copy prompt copied ${JSON.stringify(copied)}`);
  dialogs.answer = true;
  dialogs.promptText = "Lantern Town";
  await page.click("#template-detail button:has-text('Duplicate')");
  await page.waitForSelector("#template-editor:not([hidden])");
  const json = await page.inputValue("#template-json");
  await page.fill("#template-json", json.replace('"default_tempo": 88', '"default_tempo": 92'));
  await page.click("#template-save");
  await waitText("#template-detail", "92 BPM");
  await waitText("#template-list", "Lantern Town");
  await page.click("#template-detail button:has-text('Delete')");
  await page.waitForFunction(() => !document.querySelector("#template-list").textContent.includes("Lantern Town"));
  dialogs.answer = null;
  step("templates: view chart, copy prompt over plain HTTP, duplicate, edit tempo, delete");
  await page.click("#tabs .tab[data-view=songs]");

  // Help page: reachable from the header, recipes have Copy buttons, links back work.
  await page.click("#tabs a.tab[href='help.html']");
  await page.waitForURL(/help\.html$/);
  const recipes = await page.locator(".recipe .copy").count();
  if (recipes < 10) throw new Error(`help page shows only ${recipes} recipes`);
  await page.click("a.tab[href='setup.html']");
  await page.waitForURL(/setup\.html$/);
  const setupRecipes = await page.locator(".recipe .copy").count();
  const configHref = await page.getAttribute("a[data-mcp-config=antigravity]", "href");
  if (!configHref || !configHref.includes("client=antigravity&token=")) throw new Error(`setup config link ${configHref}`);
  if (await page.isVisible("[data-needs-login]")) throw new Error("login note shown while logged in");
  if (setupRecipes < 15) throw new Error(`setup page shows only ${setupRecipes} copyable commands`);
  await page.click("a.tab[href='help.html']");
  await page.waitForURL(/help\.html$/);
  await page.click("a.tab[href='./#templates']");
  await page.waitForSelector("#templates-view:not([hidden])");
  await page.click("#tabs .tab[data-view=songs]");
  step(`help page: ${recipes} copyable recipes, Templates link opens the templates tab`);

  if (shot) await page.screenshot({ path: shot, fullPage: true });
  await page.reload();
  await page.waitForSelector("#app:not([hidden])");
  if (await page.inputValue("#download-format") !== "mp3:320") throw new Error("download format not remembered");
  step("token and download format remembered after reload");

  if (errors.length) throw new Error(`browser errors: ${errors.join(" | ")}`);
  console.log("E2E UI PASSED");
} catch (error) {
  if (shot) await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
  console.error(`E2E FAILED: ${error.message}\n${errors.join("\n")}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
