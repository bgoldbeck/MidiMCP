// Templates page: browse built-in and custom templates; duplicate, edit (JSON) and delete custom ones.
import { ApiError } from "./api.js";

const NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const noteName = (pitch) => `${NOTE_NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`;

export function setupTemplates({ api, el, showError, instrumentName }) {
  const $ = (id) => document.getElementById(id);
  let current = null;

  async function refreshList(selectId = current?.id) {
    const { templates } = await api.templates();
    $("template-list").replaceChildren(...templates.map((t) => el("li", {
      class: t.id === selectId ? "active" : "",
      "data-template": t.id,
      onclick: () => open(t.id).catch(showError),
    },
    el("span", { class: "title" }, t.name, el("span", { class: t.builtIn ? "badge" : "badge custom", text: t.builtIn ? "built-in" : "custom" })),
    el("span", { class: "sub", text: `${t.meter} · ${t.tempoBpm} BPM · ${t.mode} · ${t.bars} bars` }))));
  }

  function list(items) {
    return el("ul", {}, items.map((text) => el("li", { text })));
  }

  async function open(id) {
    current = await api.template(id);
    $("template-empty").hidden = true;
    $("template-editor").hidden = true;
    $("template-detail").hidden = false;
    for (const li of $("template-list").children) li.classList.toggle("active", li.dataset.template === id);
    render(current);
  }

  function render(t) {
    const prompt = `Using the midimcp tools, create a song from the "${t.id}" template titled "My ${t.name} Theme". ` +
      "Fill every section of every track following the chord chart and the template guidance, " +
      "then validate, fix the warnings that make sense, and render a preview.";
    const actions = el("div", { class: "buttons" },
      el("button", { class: "secondary", onclick: duplicate }, "Duplicate"),
      t.builtIn ? null : el("button", { class: "secondary", onclick: edit }, "Edit"),
      t.builtIn ? null : el("button", { class: "danger", onclick: remove }, "Delete"));
    $("template-detail").replaceChildren(el("div", { class: "tpl-detail" },
      el("div", { class: "song-head" },
        el("div", {},
          el("h2", {}, t.name, el("span", { class: t.builtIn ? "badge" : "badge custom", text: t.builtIn ? "built-in" : "custom" })),
          el("p", { class: "meta", text: t.summary }),
          el("p", { class: "meta", text: `${t.default_tempo} BPM (range ${t.tempo_range[0]}–${t.tempo_range[1]}) · ${t.meter[0]}/${t.meter[1]} · ${t.default_tonic} ${t.mode} (also: ${t.alternative_modes.join(", ") || "–"}) · ${t.formBars} bars · ${t.loop ? "loops" : "no loop"} · ${t.percussion_allowed ? "percussion allowed" : "no percussion"}` }),
          el("p", { class: "meta", text: `Mood: ${t.mood}. Setting: ${t.setting}.` })),
        actions),
      el("h3", { text: "Ensemble" }),
      el("table", { class: "tpl-table" },
        el("thead", {}, el("tr", {}, ["Role", "Track", "Instrument", "Range", "Max notes", "What it plays"].map((h) => el("th", { text: h })))),
        el("tbody", {}, t.parts.map((p) => el("tr", {},
          el("td", { text: p.role }), el("td", { text: p.name }), el("td", { text: instrumentName(p.instrument_id) }),
          el("td", { text: `${noteName(p.lowest)}–${noteName(p.highest)}` }), el("td", { text: p.max_polyphony }),
          el("td", { text: p.guidance }))))),
      el("h3", { text: `Form and chords (in ${t.default_tonic})` }),
      el("table", { class: "tpl-table" },
        el("thead", {}, el("tr", {}, ["Section", "Bars", "Chords (one per bar, repeating)", "Purpose"].map((h) => el("th", { text: h })))),
        el("tbody", {}, t.chart.map((s) => el("tr", {},
          el("td", { text: s.label }), el("td", { text: s.bars }),
          el("td", {}, el("div", { class: "chords", text: s.chords.join("  ") }), el("div", { class: "numerals", text: s.numerals.join("  ") })),
          el("td", { text: s.intent }))))),
      el("h3", { text: "Melody" }), el("p", { text: t.melody }),
      el("h3", { text: "Accompaniment" }), el("p", { text: t.accompaniment }),
      Object.keys(t.patterns).length ? el("h3", { text: "Patterns" }) : null,
      Object.keys(t.patterns).length ? list(Object.entries(t.patterns).map(([k, v]) => `${k}: ${v}`)) : null,
      el("h3", { text: "Do" }), list(t.dos),
      el("h3", { text: "Don't" }), list(t.donts),
      el("h3", { text: "Prompt to use it" }),
      el("div", { class: "prompt-box", id: "template-prompt", text: prompt }),
      el("div", { class: "buttons" }, el("button", {
        class: "secondary small",
        onclick: (e) => navigator.clipboard?.writeText(prompt).then(() => { e.target.textContent = "Copied"; }),
      }, "Copy prompt"))));
  }

  async function duplicate() {
    const name = window.prompt("Name for your copy:", `${current.name} (mine)`);
    if (!name) return;
    const base = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "template";
    try {
      const copy = await api.duplicateTemplate(current.id, base, name);
      await refreshList(copy.id);
      await open(copy.id);
      edit();
    } catch (error) {
      showError(error);
    }
  }

  function edit() {
    const editable = { ...current };
    for (const key of ["builtIn", "chart", "formBars", "ticksPerBar"]) delete editable[key];
    $("template-json").value = JSON.stringify(editable, null, 2);
    $("template-status").textContent = "";
    $("template-editor").hidden = false;
    $("template-json").focus();
  }

  async function save() {
    let data;
    try {
      data = JSON.parse($("template-json").value);
    } catch (error) {
      $("template-status").textContent = `Not valid JSON: ${error.message}`;
      return;
    }
    try {
      current = await api.saveTemplate(current.id, data);
      $("template-status").textContent = "Saved.";
      $("template-editor").hidden = true;
      render(current);
      await refreshList(current.id);
    } catch (error) {
      $("template-status").textContent = error instanceof ApiError ? error.message : String(error);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete the template "${current.name}"? Songs already made from it are not affected.`)) return;
    try {
      await api.deleteTemplate(current.id);
      current = null;
      $("template-detail").hidden = true;
      $("template-editor").hidden = true;
      $("template-empty").hidden = false;
      await refreshList();
    } catch (error) {
      showError(error);
    }
  }

  $("template-save").onclick = save;
  $("template-cancel").onclick = () => { $("template-editor").hidden = true; };
  return { refreshList, open };
}
