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

## Nightly backup (T-072)

A launchd job snapshots `app.db` to iCloud Drive nightly at 02:00. The plist and
its paths assume the repo is at `~/Desktop/PROJECTS/case-prep`; edit
`scripts/backup_launchd.plist` if it lives elsewhere. Install once:

```sh
cp scripts/backup_launchd.plist ~/Library/LaunchAgents/com.caseprep.backup.plist
launchctl load ~/Library/LaunchAgents/com.caseprep.backup.plist
launchctl start com.caseprep.backup          # run once now to verify
```

**Verify (manual checklist):**

- [ ] `launchctl list | grep com.caseprep.backup` shows the job.
- [ ] After `launchctl start …`, a dated `app-YYYY-MM-DD.db` exists under
      `~/Library/Mobile Documents/com~apple~CloudDocs/caseprep-backups/`.
- [ ] `backup.log` in the repo root records the run with a timestamp.
- [ ] `sqlite3 <that-file> 'PRAGMA integrity_check;'` prints `ok`.
- [ ] After one overnight cycle, a fresh dated copy has appeared.

Unload with `launchctl unload ~/Library/LaunchAgents/com.caseprep.backup.plist`.

## Docs

Start with `docs/README.md`. Work items live in `docs/06_TASK_QUEUE.md`; coding
standards in `docs/04_ENGINEERING_RULES.md`.
