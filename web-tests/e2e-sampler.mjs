// Mutates only browser-test-song in a seeded LOCAL server. Never run on production.
// Usage: PLAYWRIGHT_CHANNEL=msedge node web-tests/e2e-sampler.mjs <base> <token> [screenshot]
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const {chromium}=createRequire(import.meta.url)("playwright");
const [base,token,screenshot]=process.argv.slice(2);
const id="browser-test-song";
async function api(method,path,body) {
  const response=await fetch(base+path,{method,headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});
  const data=await response.json();assert.equal(response.ok,true,JSON.stringify(data));return data;
}
const read=()=>api("GET",`/api/projects/${id}`);
let state=await read();
for (const lock of state.brief.locks) {await api("DELETE",`/api/projects/${id}/locks/${lock.id}`,{expectedRevision:state.revision});state=await read();}
await api("POST",`/api/projects/${id}/restore`,{expectedRevision:state.revision,revision:3});
const baseline=await read();
const patches=(await api("GET","/api/sampler-patches")).patches;
const patch=patches.find(p=>p.id==="vsco-flute-controlled");assert.ok(patch?.available,JSON.stringify(patches));
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{}),args:["--autoplay-policy=no-user-gesture-required"]});
const page=await browser.newPage({viewport:{width:1440,height:1050}});
const errors=[];page.on("pageerror",e=>errors.push(e.message));
async function changed(after) {
  await page.waitForFunction(rev=>Number(document.getElementById("revision").textContent.replace(/\D/g,""))>rev,after,{timeout:60000});
  await page.waitForFunction(()=>!document.querySelector(".editor-status")?.textContent.includes("Saving"));
  return read();
}
try {
  await page.addInitScript(t=>localStorage.setItem("midimcp.token",t),token);
  await page.goto(`${base}/ui/#${id}`);
  const source=page.getByLabel("Sound source for Flute",{exact:true});await source.waitFor();
  await source.selectOption(patch.id);state=await changed(baseline.revision);
  assert.deepEqual(state.score.tracks[0].sampler,{patchId:patch.id,patchSha256:patch.sha256});
  await page.reload();await source.waitFor();assert.equal(await source.inputValue(),patch.id);
  await page.getByRole("button",{name:"Edit notes in Flute",exact:true}).click();
  await page.getByText("Flute performance",{exact:true}).click();
  await page.getByLabel("Held-note swell",{exact:true}).fill("12");
  await page.getByLabel("Breath gap (ticks)",{exact:true}).fill("180");
  const beforePerformance=state;
  await page.getByRole("button",{name:"Apply flute performance",exact:true}).click();
  state=await changed(state.revision);
  assert.deepEqual(state.score.tracks[0].notes.map(n=>n.pitch),beforePerformance.score.tracks[0].notes.map(n=>n.pitch));
  assert.ok(state.score.tracks[0].automation.expression.length>0);
  assert.equal(state.revision,beforePerformance.revision+1);
  await page.getByRole("button",{name:"Undo",exact:true}).click();state=await changed(state.revision);
  assert.deepEqual(state.score.tracks[0],beforePerformance.score.tracks[0]);
  await page.getByRole("button",{name:"Reset sound source of Flute to default",exact:true}).click();state=await changed(state.revision);
  assert.equal(state.score.tracks[0].sampler??null,null);
  assert.equal(await source.inputValue(),"");
  await source.selectOption(patch.id);state=await changed(state.revision);
  await page.waitForFunction(()=>document.getElementById("player-state").textContent==="ready",null,{timeout:120000});
  assert.deepEqual(errors,[]);
  if(screenshot)await page.screenshot({path:screenshot,fullPage:true});
  console.log("SAMPLER E2E PASSED: source persistence, atomic performance, undo, reset and real render");
} finally {await browser.close();}
