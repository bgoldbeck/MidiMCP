import test from "node:test";
import assert from "node:assert/strict";
import { Api } from "../src/midimcp/web/api.js";

test("editor API carries expected revisions, exact operations and protected paths", async () => {
  const calls = [];
  const api = new Api({ token: "test", fetchImpl: async (url, init) => {
    calls.push({ url, method: init.method, body: JSON.parse(init.body) });
    return { ok: true, json: async () => ({ ok: true, revision: 9 }) };
  }});
  const body = { expectedRevision: 8, operations: [{ op: "update", noteId: "n1", durationTicks: 1920 }], extendToTick: 5000 };
  await api.editNotes("a/b", body);
  await api.lock("a/b", { expectedRevision: 9, trackId: "flute", startTick: 0, endTick: 960 });
  await api.unlock("a/b", "lock/1", { expectedRevision: 10 });
  await api.setArrangement("a/b", { expectedRevision: 11, loopEnabled: true, loopStartBar: 1, loopEndBar: 2 });
  assert.deepEqual(calls.map(c => [c.url, c.method]), [
    ["/api/projects/a%2Fb/notes", "POST"],
    ["/api/projects/a%2Fb/locks", "POST"],
    ["/api/projects/a%2Fb/locks/lock%2F1", "DELETE"],
    ["/api/projects/a%2Fb/arrangement", "POST"],
  ]);
  assert.deepEqual(calls[0].body, body);
});
