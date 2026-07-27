// Chat pane + session controls (T-041). One session at a time; the server owns
// all state, we render whatever state() returns and drive it via /action.
"use strict";

const $ = (id) => document.getElementById(id);
let sessionId = null;

// --- library ----------------------------------------------------------------

async function loadLibrary() {
  const lib = await (await fetch("/api/content")).json();
  const box = $("content-list");
  box.innerHTML = "";
  box.append(
    group("Cases", lib.cases),
    group("Lessons", lib.lessons),
    group("Guesstimates", lib.guesstimates),
  );
}

function group(label, items) {
  const wrap = document.createElement("div");
  wrap.className = "group";
  wrap.innerHTML = `<h3>${label}</h3>`;
  for (const it of items) {
    const row = document.createElement("div");
    row.className = "row";
    const btn = document.createElement("button");
    btn.textContent = it.title || it.id;
    const mode = modeSelect(it.modes);
    btn.addEventListener("click", () => start(it.id, mode ? mode.value : "standard"));
    row.append(btn);
    if (mode) row.append(mode);
    wrap.append(row);
  }
  return wrap;
}

function modeSelect(modes) {
  if (!modes || modes.length < 2) return null;
  const sel = document.createElement("select");
  for (const m of modes) sel.append(new Option(m, m));
  return sel;
}

// --- session ----------------------------------------------------------------

async function start(contentId, mode) {
  const res = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content_id: contentId, mode }),
  });
  if (!res.ok) return alert("Could not start: " + (await res.text()));
  const state = await res.json();
  sessionId = state.session_id;
  $("library").hidden = true;
  $("session").hidden = false;
  $("transcript").innerHTML = "";
  render(state);
}

function quit() {
  sessionId = null;
  $("session").hidden = true;
  $("library").hidden = false;
}

async function act(action, value) {
  const res = await fetch(`/api/session/${sessionId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, value: value ?? null }),
  });
  render(await res.json());
}

// --- transcript + streaming -------------------------------------------------

function addTurn(role, text) {
  const el = document.createElement("div");
  el.className = "turn " + role;
  el.textContent = text;
  $("transcript").append(el);
  el.scrollIntoView();
  return el;
}

async function sendMessage(text) {
  addTurn("user", text);
  const el = addTurn("assistant", "");
  const res = await fetch(`/api/session/${sessionId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split("\n\n");
    buf = events.pop();
    for (const evt of events) {
      const line = evt.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") return;
      el.textContent += JSON.parse(payload).token;
    }
  }
}

// --- rendering by content type ----------------------------------------------

function render(state) {
  const view = $("view");
  const controls = $("controls");
  view.innerHTML = "";
  controls.innerHTML = "";
  $("composer").hidden = false;
  if (state.error) note(view, "⚠ " + state.error);
  ({ case: renderCase, lesson: renderLesson, guess: renderGuess })[state.type](
    state,
    view,
    controls,
  );
}

function renderCase(s, view, controls) {
  if (s.done) {
    $("composer").hidden = true;
    note(view, "Case complete");
    addTurn("model", "Model answer\n\n" + s.model_answer);
    if (s.feedback) addTurn("model", s.feedback);
    return;
  }
  if (s.prompt) note(view, s.prompt);
  note(view, "Phase: " + s.phase + (s.last ? " (final)" : ""));
  if (s.coaching) note(view, "Coach: " + s.coaching);
  if (s.coach_reveal) addTurn("model", "Model approach\n\n" + s.coach_reveal);
  if (s.mode === "guided") button(controls, "Reveal approach", () => act("reveal"));
  button(controls, s.last ? "Finish" : "Next phase", () => act("advance"));
}

function renderLesson(s, view, controls) {
  if (s.stage === "teaching") {
    note(view, s.heading);
    note(view, s.content);
    if (s.worked_example) note(view, "Example: " + s.worked_example);
    button(controls, "Next", () => act("advance"));
  } else if (s.stage === "quiz") {
    $("composer").hidden = true;
    note(view, s.question);
    for (const opt of s.options) button(controls, opt, () => act("answer", opt));
    if (s.correct !== undefined) {
      note(view, (s.correct ? "✓ Correct. " : "✗ Not quite. ") + s.explanation);
    }
  } else {
    $("composer").hidden = true;
    const c = s.coverage;
    note(view, `Done. Quiz ${c.quiz_correct}/${c.quiz_total}.`);
    note(view, "Concepts: " + c.concepts.join(", "));
  }
}

function renderGuess(s, view, controls) {
  if (s.prompt) note(view, s.prompt);
  if (s.done) {
    $("composer").hidden = true;
    note(view, "Complete. Your estimates:");
    for (const e of s.estimates) note(view, `${e.segment}: ${e.value}`);
    return;
  }
  note(view, "Step: " + s.step);
  if (s.step === "estimation") {
    note(view, "Estimate for: " + s.segment);
    const input = document.createElement("input");
    input.type = "number";
    input.placeholder = "your number";
    controls.append(input);
    button(controls, "Submit estimate", () => act("estimate", input.value));
  } else {
    button(controls, "Next step", () => act("advance"));
  }
}

// --- small helpers ----------------------------------------------------------

function note(parent, text) {
  const el = document.createElement("p");
  el.className = "note";
  el.textContent = text;
  parent.append(el);
}

function button(parent, label, onClick) {
  const b = document.createElement("button");
  b.textContent = label;
  b.addEventListener("click", onClick);
  parent.append(b);
}

$("quit-btn").addEventListener("click", quit);
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("message");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendMessage(text);
});

loadLibrary();
