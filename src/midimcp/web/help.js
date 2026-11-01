// Help page: add a Copy button to every prompt recipe.
for (const recipe of document.querySelectorAll(".recipe")) {
  const text = recipe.querySelector("pre").textContent;
  const button = document.createElement("button");
  button.className = "secondary small copy";
  button.textContent = "Copy";
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
    } catch {
      const range = document.createRange();
      range.selectNodeContents(recipe.querySelector("pre"));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      button.textContent = "Selected – press Ctrl+C";
    }
    setTimeout(() => { button.textContent = "Copy"; }, 2500);
  });
  recipe.append(button);
}
