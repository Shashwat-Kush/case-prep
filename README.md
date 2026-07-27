# CasePrep Local

A voice-enabled case-interview learning and practice tool for a single user on a
MacBook Air M2. Cloud-first LLM inference on free tiers (Groq → Nvidia → Ollama),
local Piper TTS, FastAPI backend, browser frontend. All content is validated JSON
on disk (see `docs/`).

## Setup

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in GROQ_API_KEY, NVIDIA_API_KEY
```

## Run

```sh
python -m app.main          # (Phase 3+) FastAPI server
python -m app.cli           # (Phase 1) terminal chat REPL
```

## Validate content

```sh
python scripts/validate_case.py        # lists every violation, exits nonzero if any
```

Enable the pre-commit hook once so validation + ruff run automatically before
every commit (blocks the commit if content is invalid or code is lint/format-dirty):

```sh
git config core.hooksPath .githooks
```

## Docs

Start with `docs/README.md`. Work items live in `docs/06_TASK_QUEUE.md`; coding
standards in `docs/04_ENGINEERING_RULES.md`.
