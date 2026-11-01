// Thin client for the MidiMCP web API. The access token is kept in localStorage.

const TOKEN_KEY = "midimcp.token";

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `HTTP ${status}`);
    this.status = status;
    this.code = body?.code || "HTTP_ERROR";
    this.body = body || {};
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: token lives only for this page */
  }
}

export class Api {
  constructor({ base = "", token = getToken(), fetchImpl = (...a) => fetch(...a) } = {}) {
    this.base = base;
    this.token = token;
    this.fetch = fetchImpl;
  }

  async request(method, path, body) {
    const headers = { Authorization: `Bearer ${this.token}` };
    const init = { method, headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const response = await this.fetch(this.base + path, init);
    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    if (!response.ok) throw new ApiError(response.status, data);
    return data;
  }

  /** URL usable by <audio>, <a download> and WebSocket (they cannot send headers). */
  url(path) {
    const sep = path.includes("?") ? "&" : "?";
    return `${this.base}${path}${sep}token=${encodeURIComponent(this.token)}`;
  }

  status() { return this.request("GET", "/api/status"); }
  projects(search = "") {
    const q = search ? `?search=${encodeURIComponent(search)}` : "";
    return this.request("GET", `/api/projects${q}`);
  }
  project(id, revision) {
    const q = revision ? `?revision=${revision}` : "";
    return this.request("GET", `/api/projects/${encodeURIComponent(id)}${q}`);
  }
  deleteProject(id) { return this.request("DELETE", `/api/projects/${encodeURIComponent(id)}`); }
  revisions(id) { return this.request("GET", `/api/projects/${encodeURIComponent(id)}/revisions`); }
  instruments(search = "") {
    const q = search ? `?search=${encodeURIComponent(search)}` : "";
    return this.request("GET", `/api/instruments${q}`);
  }
  updateTrack(id, trackId, changes) {
    return this.request(
      "PATCH",
      `/api/projects/${encodeURIComponent(id)}/tracks/${encodeURIComponent(trackId)}`,
      changes,
    );
  }
  templates() { return this.request("GET", "/api/templates"); }
  template(id) { return this.request("GET", `/api/templates/${encodeURIComponent(id)}`); }
  saveTemplate(id, data) { return this.request("PUT", `/api/templates/${encodeURIComponent(id)}`, data); }
  deleteTemplate(id) { return this.request("DELETE", `/api/templates/${encodeURIComponent(id)}`); }
  duplicateTemplate(id, newId, name) {
    return this.request("POST", `/api/templates/${encodeURIComponent(id)}/duplicate`, { newId, name });
  }
  collections() { return this.request("GET", "/api/collections"); }
  createCollection(name) { return this.request("POST", "/api/collections", { name }); }
  renameCollection(id, name) { return this.request("PATCH", `/api/collections/${encodeURIComponent(id)}`, { name }); }
  deleteCollection(id) { return this.request("DELETE", `/api/collections/${encodeURIComponent(id)}`); }
  organization(id) { return this.request("GET", `/api/projects/${encodeURIComponent(id)}/organization`); }
  setOrganization(id, body) { return this.request("PUT", `/api/projects/${encodeURIComponent(id)}/organization`, body); }
  resetTrack(id, trackId, body) {
    return this.request(
      "POST",
      `/api/projects/${encodeURIComponent(id)}/tracks/${encodeURIComponent(trackId)}/reset`,
      body,
    );
  }
  restore(id, expectedRevision, revision) {
    return this.request("POST", `/api/projects/${encodeURIComponent(id)}/restore`, {
      expectedRevision,
      revision,
    });
  }
  render(id, options = {}) {
    return this.request("POST", `/api/projects/${encodeURIComponent(id)}/render`, options);
  }
  job(jobId) { return this.request("GET", `/api/jobs/${encodeURIComponent(jobId)}`); }
  exports(id) { return this.request("GET", `/api/projects/${encodeURIComponent(id)}/exports`); }
  createExport(id, format, options = {}) {
    return this.request("POST", `/api/projects/${encodeURIComponent(id)}/exports`, {
      format,
      ...options,
    });
  }

  /** Poll a render job until it finishes. Resolves with the job, rejects on failure. */
  async waitForJob(job, { intervalMs = 300, timeoutMs = 600000, sleep = defaultSleep } = {}) {
    const started = Date.now();
    let current = job;
    while (current.status === "queued" || current.status === "running") {
      if (Date.now() - started > timeoutMs) throw new ApiError(504, { code: "RENDER_TIMEOUT", message: "render took too long" });
      await sleep(intervalMs);
      current = await this.job(current.jobId);
    }
    if (current.status !== "completed") {
      throw new ApiError(422, current.error || { code: "RENDER_FAILED", message: "render failed" });
    }
    return current;
  }

  events(onEvent, { WebSocketImpl = globalThis.WebSocket, location = globalThis.location } = {}) {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocketImpl(
      `${scheme}://${location.host}${this.base}/api/events?token=${encodeURIComponent(this.token)}`,
    );
    socket.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data));
      } catch {
        /* ignore malformed frames */
      }
    };
    return socket;
  }
}

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
