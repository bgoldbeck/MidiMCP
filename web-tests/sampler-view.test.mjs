import test from "node:test";
import assert from "node:assert/strict";
import { sourceOptions, samplerBinding } from "../src/midimcp/web/sampler-view.js";

const patches=[{id:"flute",name:"Sampled flute",sha256:"abc",available:true},{id:"absent",name:"Other flute",available:false}];
test("sound source options retain a missing or changed pinned source without substituting",()=>{
  const options=sourceOptions({sampler:{patchId:"flute",patchSha256:"old"}},patches);
  assert.equal(options.filter(o=>o.selected).length,1);
  assert.equal(options.find(o=>o.selected).disabled,true);
  assert.match(options.find(o=>o.selected).label,/unavailable|changed/i);
  assert.equal(options.find(o=>o.value==='absent').disabled,true);
});
test("choosing a sampled source pins the hash and choosing GM explicitly clears it",()=>{
  assert.deepEqual(samplerBinding("flute",patches),{patchId:"flute",patchSha256:"abc"});
  assert.equal(samplerBinding("",patches),null);
  assert.throws(()=>samplerBinding("absent",patches),/unavailable/i);
  assert.equal(sourceOptions({},patches)[0].selected,true);
});
