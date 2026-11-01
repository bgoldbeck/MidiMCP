// End-to-end browser check of the player page against a running server.
// Usage: node web-tests/e2e-player.mjs <baseUrl> <token> <projectTitle> [screenshotPath]
import { createRequire } from "node:module";

// Resolve playwright like require() does (honours NODE_PATH / global installs).
const { chromium } = createRequire(import.meta.url)("playwright");

const [base, token, title, shot] = process.argv.slice(2);
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const step = (msg) => console.log(`step: ${msg}`);

try {
  await page.goto(base + "/");
  await page.waitForURL(/\/ui\/$/);
  step("redirected to /ui/");

  await page.fill("#token-input", "wrong-token-123456789");
  await page.click("#login-form button");
  await page.waitForSelector("#login-error:not([hidden])");
  step("wrong token rejected");
  errors.length = 0; // the expected 401 from the wrong token is logged by the browser

  await page.fill("#token-input", token);
  await page.click("#login-form button");
  await page.waitForSelector("#app:not([hidden])");
  step("logged in");

  const option = page.locator("#project-select option", { hasText: title });
  await option.waitFor({ state: "attached" });
  await page.selectOption("#project-select", { label: await option.textContent() });
  await page.waitForFunction(() => document.querySelector("#player-state").textContent === "ready", null, { timeout: 60000 });
  step(`loaded: ${await page.textContent("#song-meta")}`);

  await page.click("#play");
  await page.waitForFunction(() => document.querySelector("#player-state").textContent === "playing");
  await page.waitForFunction(() => document.querySelector("#time").textContent !== "0:00", null, { timeout: 10000 });
  step(`playing, time ${await page.textContent("#time")}, bar ${await page.textContent("#bar")}`);

  const srcBefore = await page.evaluate(() => document.querySelector("#audio").src);
  await page.selectOption("#speed", "1.25");
  await page.waitForFunction((before) => document.querySelector("#audio").src !== before, srcBefore, { timeout: 60000 });
  await page.waitForFunction(() => document.querySelector("#player-state").textContent === "playing", null, { timeout: 60000 });
  step("speed 125% re-rendered and still playing");

  await page.click("#pause");
  await page.waitForFunction(() => document.querySelector("#player-state").textContent === "paused");
  await page.click("#stop");
  await page.waitForFunction(() => document.querySelector("#bar").textContent === "1");
  step("pause and stop work");

  await page.reload();
  await page.waitForSelector("#app:not([hidden])");
  step("token remembered after reload");

  if (shot) await page.screenshot({ path: shot, fullPage: true });
  if (errors.length) throw new Error(`browser errors: ${errors.join(" | ")}`);
  console.log("E2E PLAYER PASSED");
} catch (error) {
  if (shot) await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
  console.error(`E2E FAILED: ${error.message}\n${errors.join("\n")}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
