// Copy text to the clipboard. Works on plain-HTTP LAN addresses too, where browsers
// disable navigator.clipboard (it only exists on HTTPS and localhost).
// Returns "copied", or "selected" when the text could only be selected for Ctrl+C.

export async function copyText(text, fallbackNode) {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return "copied";
    } catch {
      // fall through to the legacy path
    }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.top = "-1000px";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  if (ok) return "copied";
  if (fallbackNode) {
    const range = document.createRange();
    range.selectNodeContents(fallbackNode);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
  }
  return "selected";
}

export function flashCopyResult(button, result, label) {
  button.textContent = result === "copied" ? "Copied" : "Selected – press Ctrl+C";
  setTimeout(() => { button.textContent = label; }, 2500);
}
