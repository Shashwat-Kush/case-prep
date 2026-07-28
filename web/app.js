// Chat pane + session controls (T-041). One session at a time; the server owns
// all state, we render whatever state() returns and drive it via /action.
"use strict";

const $ = (id) => document.getElementById(id);
let sessionId = null;
let timerId = null;
let voiceTurn = false; // set when the pending turn came from the mic (T-053)

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
  const h = document.createElement("h3");
  h.textContent = label;
  const count = document.createElement("span");
  count.className = "count";
  count.textContent = items.length;
  h.append(" ", count);
  wrap.append(h);
  for (const it of items) wrap.append(itemCard(it));
  return wrap;
}

// A descriptive library card: title, one-line blurb, metadata badges, and Start.
function itemCard(it) {
  const card = document.createElement("div");
  card.className = "item";

  const main = document.createElement("div");
  main.className = "item-main";
  const title = document.createElement("div");
  title.className = "item-title";
  title.textContent = it.title || it.id;
  main.append(title);
  if (it.blurb) {
    const blurb = document.createElement("div");
    blurb.className = "item-blurb";
    blurb.textContent = it.blurb;
    main.append(blurb);
  }
  const meta = document.createElement("div");
  meta.className = "item-meta";
  for (const b of itemBadges(it)) {
    const span = document.createElement("span");
    span.className = "badge" + (b === "diagnostic" ? " badge-diag" : "");
    span.textContent = b;
    meta.append(span);
  }
  main.append(meta);
  card.append(main);

  const actions = document.createElement("div");
  actions.className = "item-actions";
  const mode = modeSelect(it.modes);
  if (mode) actions.append(mode);
  const startBtn = document.createElement("button");
  startBtn.className = "btn-primary";
  startBtn.textContent = "Start →";
  startBtn.addEventListener("click", () =>
    start(it.id, mode ? mode.value : "standard"),
  );
  actions.append(startBtn);
  card.append(actions);
  return card;
}

function itemBadges(it) {
  const b = [];
  if (it.difficulty) b.push(it.difficulty);
  if (it.minutes) b.push(`~${it.minutes} min`);
  if (it.type) b.push(it.type);
  if (it.industry) b.push(it.industry);
  if (it.region) b.push(it.region);
  if (it.concepts) b.push(`${it.concepts} concepts`);
  if (it.diagnostic) b.push("diagnostic");
  return b;
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
  stopAudio();
  $("number-confirm").hidden = true;
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
  if (s.hint) addTurn("model", "💡 Hint: " + s.hint); // T-065; costs score
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
  $("number-confirm").hidden = true;
  const speak = voiceTurn; // only voice turns are spoken back (typed skip TTS)
  voiceTurn = false;
  addTurn("user", text);
  const el = addTurn("assistant", "");
  const res = await fetch(`/api/session/${sessionId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, speak }),
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
      const obj = JSON.parse(payload);
      if (obj.audio) enqueueAudio(obj.audio); // spoken sentence (T-053)
      else if (obj.token != null) el.textContent += obj.token;
    }
  }
}

// --- rendering by content type ----------------------------------------------

// The composer (input + mic + Send) and its hint show/hide together.
function showComposer(v) {
  $("composer").hidden = !v;
  $("composer-hint").hidden = !v;
}

function render(state) {
  const view = $("view");
  const controls = $("controls");
  clearInterval(timerId);
  timerId = null;
  view.innerHTML = "";
  controls.innerHTML = "";
  showComposer(true);
  if (state.error) note(view, "⚠ " + state.error);
  ({ case: renderCase, lesson: renderLesson, guess: renderGuess })[state.type](
    state,
    view,
    controls,
  );
}

const PHASE_HINTS = {
  opening: "Restate the problem and objective in one line, then Send.",
  clarifying: "Ask a few sharp clarifying questions before diving in.",
  structuring: "Lay out your framework (a clean, MECE tree). Send it, then continue.",
  analysis: "Work the drivers. Ask about the data to unlock exhibits.",
  math: "Do the arithmetic out loud — state your numbers so they can be checked.",
  synthesis: "Give a recommendation: name the driver, an action, and one risk.",
};

function renderCase(s, view, controls) {
  if (s.done) {
    showComposer(false);
    note(view, "✓ Case complete — here's the model answer and your feedback.");
    if (s.overruns && s.overruns.length) {
      note(view, "⏱ Pacing: you overran " + s.overruns.join(", ") + ".");
    }
    addTurn("model", "Model answer\n\n" + s.model_answer);
    if (s.feedback) addTurn("model", s.feedback);
    button(controls, "Review session", showReview).classList.add("btn-primary");
    return;
  }
  stepper(view, s.phases || [s.phase], s.phase);
  if (s.prompt) promptBlock(view, s.prompt);
  hintBox(
    view,
    PHASE_HINTS[s.phase] ||
      "Type or speak your answer, then Send. Click Next phase → when ready.",
  );
  startTimer(view, s.time_budget_s);
  if (s.coaching) note(view, "🎓 Coach: " + s.coaching);
  if (s.coach_reveal) addTurn("model", "Model approach\n\n" + s.coach_reveal);
  for (const id of s.exhibits || []) {
    button(controls, "📊 View exhibit: " + id, () => viewExhibit(id));
  }
  if (s.mode === "guided") button(controls, "Reveal approach", () => act("reveal"));
  if (s.mode !== "cold") button(controls, "💡 Hint (costs score)", () => act("hint"));
  const next = button(
    controls,
    s.last ? "Finish & see feedback →" : "Next phase →",
    () => act("advance"),
  );
  next.classList.add("btn-primary");
}

// The case's phases as a progress spine: done · current · upcoming.
function stepper(parent, phases, current) {
  const wrap = document.createElement("div");
  wrap.className = "stepper";
  const at = phases.indexOf(current);
  phases.forEach((name, i) => {
    const el = document.createElement("span");
    el.className =
      "step" + (i < at ? " done" : i === at ? " current" : "");
    el.textContent = (i < at ? "✓ " : "") + name;
    wrap.append(el);
  });
  parent.append(wrap);
}

function promptBlock(parent, text) {
  const el = document.createElement("p");
  el.className = "prompt";
  el.textContent = text;
  parent.append(el);
}

function hintBox(parent, text) {
  const el = document.createElement("div");
  el.className = "hint";
  el.textContent = text;
  parent.append(el);
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
    button(controls, "Next →", () => act("advance")).classList.add("btn-primary");
  } else if (s.stage === "quiz") {
    showComposer(false);
    note(view, s.question);
    for (const opt of s.options) button(controls, opt, () => act("answer", opt));
    if (s.correct !== undefined) {
      note(view, (s.correct ? "✓ Correct. " : "✗ Not quite. ") + s.explanation);
    }
  } else {
    showComposer(false);
    const c = s.coverage;
    note(view, `Done. Quiz ${c.quiz_correct}/${c.quiz_total}.`);
    note(view, "Concepts: " + c.concepts.join(", "));
  }
}

function renderGuess(s, view, controls) {
  if (s.prompt) note(view, s.prompt);
  if (s.done) {
    showComposer(false);
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
  stepper(view, ["clarify", "approach", "segmentation", "estimation"], s.step);
  if (s.step === "estimation") {
    hintBox(view, "Enter your number for this segment, then Submit estimate.");
    note(view, "Estimate for: " + s.segment);
    const input = document.createElement("input");
    input.type = "number";
    input.placeholder = "your number";
    controls.append(input);
    button(controls, "Submit estimate", () => act("estimate", input.value)).classList.add(
      "btn-primary",
    );
  } else {
    hintBox(view, "Talk through this step, then click Next step → to continue.");
    button(controls, "Next step →", () => act("advance")).classList.add("btn-primary");
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
  showComposer(false);
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

// --- dashboard (T-062) ------------------------------------------------------

async function showDashboard() {
  const d = await (await fetch("/api/dashboard")).json();
  const body = $("dash-body");
  body.innerHTML = `<h2>Progress</h2>`;
  note(
    body,
    `${d.sessions.completed} of ${d.sessions.total} sessions completed`,
  );

  const rec = document.createElement("div");
  rec.className = "group recommendation";
  rec.innerHTML = `<h3>Next step</h3><p>${d.recommendation.message}</p>`;
  body.append(rec);

  const dims = document.createElement("div");
  dims.className = "group";
  dims.innerHTML = `<h3>Score trends (bar ${d.graduation_bar}/5)</h3>`;
  if (!d.dimensions.length) note(dims, "No scored cases yet.");
  for (const dim of d.dimensions) {
    const row = document.createElement("div");
    row.className = "dim-row" + (dim.weak ? " weak" : "");
    const spark = dim.scores.map((s) => "▁▂▃▅▇"[s - 1] || "·").join("");
    row.textContent = `${dim.dimension}: ${spark} avg ${dim.avg}${dim.weak ? " ⚠" : ""}`;
    dims.append(row);
  }
  body.append(dims);

  if (d.topics.length) {
    const t = document.createElement("div");
    t.className = "group";
    t.innerHTML = `<h3>Case topics</h3>`;
    for (const top of d.topics) {
      const modes = Object.entries(top.attempts)
        .map(([m, n]) => `${n}× ${m}`)
        .join(", ");
      const avg = top.avg_score == null ? "—" : `${top.avg_score.toFixed(1)}/5`;
      note(t, `${top.topic}: ${modes} · avg ${avg}`);
    }
    body.append(t);
  }

  $("library").hidden = true;
  $("dashboard").hidden = false;
}

function closeDashboard() {
  $("dashboard").hidden = true;
  $("library").hidden = false;
}

// --- mental-math sprints (T-063) --------------------------------------------
// LLM-free; the server generates and grades, we just render prompts and inputs.

let drillId = null;
let drillStart = 0;

const startDrills = () => startSprint("/api/drills", "Mental math", { n: 5 });
const startFlashcards = () => startSprint("/api/flashcards", "Benchmarks", {});

async function startSprint(url, title, payload) {
  const d = await (
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  ).json();
  drillId = d.drill_id;
  drillStart = performance.now();
  const form = $("drills-form");
  form.innerHTML = `<h2>${title}</h2>`;
  d.items.forEach((it, i) => {
    const row = document.createElement("label");
    row.className = "dim-row";
    row.textContent = `${i + 1}. ${it.prompt} `;
    const input = document.createElement("input");
    input.inputMode = "decimal";
    input.dataset.i = i;
    row.append(input);
    form.append(row);
  });
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Grade";
  form.append(submit);
  $("drills-result").innerHTML = "";
  $("library").hidden = true;
  $("drills").hidden = false;
}

async function gradeDrills(e) {
  e.preventDefault();
  if (!drillId) return;
  const inputs = [...$("drills-form").querySelectorAll("input")];
  const answers = inputs.map((el) => {
    const v = parseFloat(el.value.replace(/,/g, ""));
    return Number.isNaN(v) ? null : v;
  });
  const res = await (
    await fetch(`/api/drills/${drillId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers, elapsed_ms: performance.now() - drillStart }),
    })
  ).json();
  inputs.forEach((el, i) => {
    const item = res.items[i];
    el.classList.toggle("wrong", !item.ok);
    if (!item.ok) el.value = `${el.value || "—"} → ${item.expected}`;
  });
  note($("drills-result"), `${res.correct}/${res.total} correct`);
  drillId = null;
}

function closeDrills() {
  drillId = null;
  $("drills").hidden = true;
  $("library").hidden = false;
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

// --- talk (T-050) -----------------------------------------------------------
// Click the mic to start recording, click again to stop; the blob uploads for
// transcription (T-051). No holding required. Typing always works too.

let recorder = null;
let audioChunks = [];

function toggleRecording() {
  if (recorder && recorder.state === "recording") stopRecording();
  else startRecording();
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    recorder = new MediaRecorder(stream);
    recorder.addEventListener("dataavailable", (e) => audioChunks.push(e.data));
    recorder.addEventListener("stop", uploadRecording);
    recorder.start();
    const mic = $("mic");
    mic.classList.add("recording");
    mic.textContent = "● Stop";
  } catch {
    alert("Microphone unavailable — please type your response instead.");
  }
}

function stopRecording() {
  const mic = $("mic");
  mic.classList.remove("recording");
  mic.textContent = "🎤 Speak";
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
    voiceTurn = true; // this reply should be spoken back (T-053)
    showNumberConfirm(out.numbers || []);
  } else {
    addTurn("model", "🎤 Couldn't transcribe that — please type your response.");
  }
}

// Confirm each number I heard before it could reach the math checker (T-052).
// Spoken numbers (fifteen/fifty…) are error-prone, so they are editable inline.
function showNumberConfirm(numbers) {
  const box = $("number-confirm");
  box.innerHTML = "";
  box.hidden = numbers.length === 0;
  if (!numbers.length) return;
  note(box, "Confirm the numbers I heard (edit or pick the right one):");
  for (const n of numbers) {
    const row = document.createElement("div");
    row.className = "row";
    const label = document.createElement("span");
    label.textContent = "“" + n.surface + "” →";
    const input = document.createElement("input");
    input.type = "number";
    input.value = n.value;
    input.addEventListener("change", () => replaceNumber(n.value, input.value));
    row.append(label, input);
    for (const c of n.candidates) {
      if (c === n.value) continue; // the alternate reading (e.g. fifty vs fifteen)
      const b = button(row, "maybe " + c, () => {
        input.value = c;
        replaceNumber(n.value, c);
      });
      b.className = "link";
    }
    box.append(row);
  }
}

function replaceNumber(from, to) {
  const msg = $("message");
  msg.value = msg.value.replace(String(from), String(to));
}

// --- spoken-reply playback (T-053) ------------------------------------------
// WAV arrives one sentence at a time; queue so sentences play in order.

let audioQueue = [];
let audioPlaying = false;

function enqueueAudio(b64) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  audioQueue.push(URL.createObjectURL(new Blob([bytes], { type: "audio/wav" })));
  if (!audioPlaying) playNextAudio();
}

function playNextAudio() {
  const url = audioQueue.shift();
  if (!url) {
    audioPlaying = false;
    return;
  }
  audioPlaying = true;
  const a = new Audio(url);
  a.onended = a.onerror = () => {
    URL.revokeObjectURL(url);
    playNextAudio();
  };
  a.play().catch(() => {
    URL.revokeObjectURL(url);
    playNextAudio();
  });
}

function stopAudio() {
  audioQueue.forEach(URL.revokeObjectURL);
  audioQueue = [];
  audioPlaying = false;
}

$("mic").addEventListener("click", toggleRecording);

$("quit-btn").addEventListener("click", quit);
$("dashboard-btn").addEventListener("click", showDashboard);
$("dash-back").addEventListener("click", closeDashboard);
$("drills-btn").addEventListener("click", startDrills);
$("flashcards-btn").addEventListener("click", startFlashcards);
$("drills-back").addEventListener("click", closeDrills);
$("drills-form").addEventListener("submit", gradeDrills);
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
