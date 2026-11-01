// Help page: add a Copy button to every prompt recipe.
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
