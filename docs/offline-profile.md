# Offline profile (Ollama)

The offline profile routes every LLM call to a local Ollama daemon, so a case
runs with no network and zero API cost. It is also the **last-resort failover
target**: even online, Ollama is last in the provider chain (`config.yaml`), so if
Groq and Nvidia both fail the router degrades to Ollama automatically (04 §5).

## One-time setup (Phase 0 step 7)

```sh
brew install ollama
ollama pull qwen2.5:3b-instruct-q4_K_M   # the model named in config.yaml
```

## Run a typed case offline

Start the daemon, then pass `--offline` (flips `config.offline` for the run, so
the router uses only local/keyless providers):

```sh
ollama serve &                                   # if not already running
python -m app.cli case-brewbar-diagnostic --offline
```

Equivalently, set `offline: true` in `config.yaml` to make it the default.

## Manual smoke checklist

Automated coverage stops at the router boundary (mocked transport); a real model
is out of scope for unit tests, so verify these by hand once per phase gate:

1. `ollama serve` is up and the model is pulled (`ollama list`).
2. `python -m app.cli <case-id> --offline` streams a reply token-by-token.
3. The case reaches its terminal phase and prints the model-answer reveal.
4. **Wi-Fi off** mid-session: the run continues (offline never touches cloud).
5. Provider on each assistant turn is `ollama` (check `app.db` `turns.provider`).

Drills (T-063, mental-math sprints) are LLM-free and unaffected by this profile —
they need neither the daemon nor the network.

## Notes

- No API key is sent to Ollama (`api_key_env: null`); the client omits the
  `Authorization` header when a provider has no key.
- The 3B local model is markedly weaker than the 70B cloud models — offline is a
  degrade path for continuity, not a quality match. Voice offline (whisper.cpp) is
  deferred (PRD V2).
