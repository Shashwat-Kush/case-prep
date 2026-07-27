// Minimal case client (T-040). POST a turn, stream the reply back over SSE.
// The server owns all state; we hold only the session id.
"use strict";

let sessionId = null;

const $ = (id) => document.getElementById(id);

async function startCase() {
  const contentId = $("content-id").value.trim();
  if (!contentId) return;
  const res = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content_id: contentId, mode: $("mode").value }),
  });
  if (!res.ok) {
    alert("Could not start: " + (await res.text()));
    return;
  }
  const data = await res.json();
  sessionId = data.session_id;
  $("prompt").textContent = data.prompt;
  $("phase").textContent = "Phase: " + data.phase;
  $("start").hidden = true;
  $("case").hidden = false;
  $("message").focus();
}

function addTurn(role, text) {
  const el = document.createElement("div");
  el.className = "turn " + role;
  el.textContent = text;
  $("transcript").appendChild(el);
  return el;
}

// Parse an SSE byte stream into token strings, appending to `el`.
async function streamReply(res, el) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split("\n\n");
    buf = events.pop(); // keep the trailing partial event
    for (const evt of events) {
      const line = evt.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") return;
      el.textContent += JSON.parse(payload).token;
    }
  }
}

async function sendMessage(text) {
  addTurn("user", text);
  const el = addTurn("assistant", "");
  const res = await fetch(`/api/session/${sessionId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  await streamReply(res, el);
}

async function advance() {
  const res = await fetch(`/api/session/${sessionId}/advance`, { method: "POST" });
  const data = await res.json();
  if (data.terminal) {
    $("phase").textContent = "Case complete";
    addTurn("model", "Model answer\n\n" + data.model_answer);
    if (data.feedback) addTurn("model", data.feedback);
    $("composer").hidden = true;
  } else {
    $("phase").textContent = "Phase: " + data.phase;
  }
}

$("start-btn").addEventListener("click", startCase);
$("next-btn").addEventListener("click", advance);
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("message");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendMessage(text);
});
