// Help page: add a Copy button to every prompt recipe.
import { getToken } from "./api.js";
import { copyText, flashCopyResult } from "./clipboard.js";

for (const recipe of document.querySelectorAll(".recipe")) {
  const pre = recipe.querySelector("pre");
  const button = document.createElement("button");
  button.className = "secondary small copy";
  button.textContent = "Copy";
  button.addEventListener("click", async () => {
    flashCopyResult(button, await copyText(pre.textContent, pre), "Copy");
  });
  recipe.append(button);
}

// Ready-made MCP client configs: real links once this browser has logged in.
const token = getToken();
for (const link of document.querySelectorAll("a[data-mcp-config]")) {
  const kind = link.dataset.mcpConfig;
  const path = kind === "tools" ? "/api/mcp-tools?download=1" : `/api/mcp-config?client=${kind}`;
  if (token) {
    link.href = `${path}&token=${encodeURIComponent(token)}`;
  } else {
    link.removeAttribute("href");
    link.classList.add("disabled");
    link.title = "Log in on the Songs page first (paste your access token once), then come back.";
  }
}
for (const note of document.querySelectorAll("[data-needs-login]")) note.hidden = Boolean(token);
