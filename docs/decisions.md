# decisions.md

Implementation-time decisions, verified provider limits, and deviations from the
handbook (04_ENGINEERING_RULES §10). Newest first.

## 2026-07-27 · Environment: broken venv pip workaround

On this machine, `python3.12 -m venv` bundles a pip whose vendored `packaging`
uses possessive-quantifier regex that this interpreter's `re` mis-evaluates, so
`Version("0.dev0")` raises `InvalidVersion` and every venv-local pip command
fails. The **base** interpreter's older pip (23.1.2) works.

Workaround used to populate `.venv`:

```sh
python3.12 -m venv .venv
/usr/local/bin/python3.12 -m pip install --target .venv/lib/python3.12/site-packages -r requirements.txt
```

Standing action item: fix the base install (`pip3.12 install --upgrade pip` from a
shell where it works, or reinstall python.org 3.12) so the README's plain
`pip install -r requirements.txt` works. Not code-blocking.

## Provider limits

Phase 0 step 5: record verified Groq/Nvidia free-tier limits here with the date
once accounts are set up (T-003). Docs elsewhere cite indicative numbers only.
