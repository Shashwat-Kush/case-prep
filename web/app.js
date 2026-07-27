// Chat pane + session controls (T-041). One session at a time; the server owns
// all state, we render whatever state() returns and drive it via /action.
"use strict";

const $ = (id) => document.getElementById(id);
let sessionId = null;
let timerId = null;

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
  clearInterval(timerId);
  timerId = null;
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
  const s = await res.json();
  if (s.check) stepCheck(s.check, s.submitted); // coached guesstimate (T-045)
  render(s);
}

// Per-step math verdict, kept in the transcript so it survives step re-renders.
function stepCheck(check, submitted) {
  const v = submitted ? submitted.value : "";
  addTurn(
    "model",
    check.ok
      ? `✓ ${check.segment}: ${v} is in the expected ballpark.`
      : `✗ ${check.segment}: ${v} looks too ${check.direction} — reconsider.`,
  );
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
      if (payload === "[DONE]") {
        refreshStatus(); // a turn may have triggered a failover
        return;
      }
      el.textContent += JSON.parse(payload).token;
    }
  }
}

// --- rendering by content type ----------------------------------------------

function render(state) {
  const view = $("view");
  const controls = $("controls");
  clearInterval(timerId);
  timerId = null;
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
    if (s.overruns && s.overruns.length) {
      note(view, "⏱ Pacing: you overran " + s.overruns.join(", ") + ".");
    }
    addTurn("model", "Model answer\n\n" + s.model_answer);
    if (s.feedback) addTurn("model", s.feedback);
    button(controls, "Review session", showReview);
    return;
  }
  if (s.prompt) note(view, s.prompt);
  note(view, "Phase: " + s.phase + (s.last ? " (final)" : ""));
  startTimer(view, s.time_budget_s);
  if (s.coaching) note(view, "Coach: " + s.coaching);
  if (s.coach_reveal) addTurn("model", "Model approach\n\n" + s.coach_reveal);
  for (const id of s.exhibits || []) {
    button(controls, "📊 " + id, () => viewExhibit(id));
  }
  if (s.mode === "guided") button(controls, "Reveal approach", () => act("reveal"));
  button(controls, s.last ? "Finish" : "Next phase", () => act("advance"));
}

// --- exhibits ---------------------------------------------------------------

async function viewExhibit(id) {
  const res = await fetch(`/api/session/${sessionId}/exhibit/${id}`);
  if (!res.ok) return alert("Exhibit unavailable: " + (await res.text()));
  const ex = await res.json();
  const wrap = document.createElement("div");
  wrap.className = "exhibit";
  wrap.innerHTML = `<h4>${ex.title}</h4>`;
  wrap.append(dataTable(ex.data));
  $("transcript").append(wrap);
  wrap.scrollIntoView();
}

function dataTable(data) {
  const table = document.createElement("table");
  if (Array.isArray(data)) {
    const cols = data.length ? Object.keys(data[0]) : [];
    table.append(rowEl(cols, "th"));
    for (const r of data) table.append(rowEl(cols.map((c) => r[c])));
  } else if (data && typeof data === "object") {
    for (const [k, v] of Object.entries(data)) table.append(rowEl([k, v]));
  } else {
    table.append(rowEl([String(data)]));
  }
  return table;
}

function rowEl(cells, tag = "td") {
  const tr = document.createElement("tr");
  for (const c of cells) {
    const el = document.createElement(tag);
    el.textContent = c;
    tr.append(el);
  }
  return tr;
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
    if (s.final_check) {
      const f = s.final_check;
      note(
        view,
        f.in_range
          ? `✓ Final ${f.value} lands in the expected range ${f.low}–${f.high}.`
          : `✗ Final ${f.value} is outside the expected range ${f.low}–${f.high}.`,
      );
    }
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

function startTimer(parent, budgetS) {
  const el = document.createElement("div");
  el.className = "timer";
  parent.append(el);
  const start = Date.now();
  const tick = () => {
    const elapsed = Math.floor((Date.now() - start) / 1000);
    el.textContent = "⏱ " + fmt(elapsed) + (budgetS ? " / " + fmt(budgetS) : "");
    el.classList.toggle("over", budgetS && elapsed > budgetS);
  };
  tick();
  timerId = setInterval(tick, 1000);
}

function fmt(s) {
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

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
  return b;
}

// --- session review (T-046) -------------------------------------------------

async function showReview() {
  const r = await (await fetch(`/api/session/${sessionId}/review`)).json();
  const view = $("view");
  clearInterval(timerId);
  timerId = null;
  view.innerHTML = "";
  $("transcript").innerHTML = "";
  $("composer").hidden = true;
  $("controls").innerHTML = "";
  note(view, `Scorecard — average ${r.average}/5`);
  for (const s of r.scores) {
    const box = document.createElement("div");
    box.className = "group";
    box.innerHTML = `<h3>${s.dimension} — ${s.score}/5</h3>`;
    for (const e of s.evidence) {
      // Each quote deep-links to the transcript turn it was lifted from.
      const b = button(box, "“" + e.quote + "”", () => jumpToTurn(e.turn_id));
      b.className = "link";
      if (e.turn_id == null) b.disabled = true;
    }
    view.append(box);
  }
  for (const t of r.transcript) {
    const el = addTurn(t.role, t.text);
    el.id = "turn-" + t.id;
  }
}

function jumpToTurn(id) {
  if (id == null) return;
  const el = document.getElementById("turn-" + id);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("highlight");
  setTimeout(() => el.classList.remove("highlight"), 1500);
}

// --- provider status indicator (T-044) --------------------------------------

async function refreshStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const el = $("provider-status");
    const provider = s.provider || (s.offline ? "offline" : "—");
    const remaining = (s.ratelimit || {})["x-ratelimit-remaining-requests"];
    el.textContent =
      "provider: " + provider + (remaining ? ` · ${remaining} req left` : "");
    el.classList.toggle("failover", s.provider && s.provider !== s.primary);
  } catch {
    /* status is best-effort; ignore transient errors */
  }
}

// --- push-to-talk (T-050) ---------------------------------------------------
// Hold the mic to record; releasing uploads the raw blob. STT lands in T-051, so
// for now a capture just confirms audio reached the backend; typing still works.

let recorder = null;
let audioChunks = [];

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    recorder = new MediaRecorder(stream);
    recorder.addEventListener("dataavailable", (e) => audioChunks.push(e.data));
    recorder.addEventListener("stop", uploadRecording);
    recorder.start();
    $("mic").classList.add("recording");
  } catch {
    alert("Microphone unavailable — please type your response.");
  }
}

function stopRecording() {
  $("mic").classList.remove("recording");
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
    recorder.stream.getTracks().forEach((t) => t.stop());
  }
}

async function uploadRecording() {
  const blob = new Blob(audioChunks, { type: "audio/webm" });
  if (!blob.size || !sessionId) return;
  const out = await (
    await fetch(`/api/session/${sessionId}/audio`, { method: "POST", body: blob })
  ).json();
  if (out.transcript) {
    $("message").value = out.transcript; // user reviews, edits, then Sends (T-052)
    $("message").focus();
  } else {
    addTurn("model", "🎤 Couldn't transcribe that — please type your response.");
  }
}

const mic = $("mic");
mic.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  startRecording();
});
mic.addEventListener("pointerup", stopRecording);
mic.addEventListener("pointerleave", stopRecording);

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
refreshStatus();
setInterval(refreshStatus, 5000);
