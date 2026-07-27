# CasePrep Local: Documentation System

A voice-enabled case interview learning and practice tool for a single beginner user on a MacBook Air M2 (8GB RAM). Cloud-first LLM inference on free API tiers (Groq primary, Nvidia fallback, Ollama offline), local Piper TTS, FastAPI backend, browser frontend, all content as validated JSON files.

## How to use this documentation (humans and AI agents)

Read in this order for a first pass: README → 01_PRD → 02_ARCHITECTURE → 08_ARCHITECTURE_DECISIONS. Then use the others as working references.

For any implementation session, the entry point is **06_TASK_QUEUE.md**: pick the next unblocked task, follow its acceptance criteria, and obey **04_ENGINEERING_RULES.md** while coding. Every "why" question is answered in **08_ARCHITECTURE_DECISIONS.md**; do not re-litigate decisions in code comments or chat, propose a new ADR instead.

## Document map

| File | Purpose | Owns |
|---|---|---|
| [01_PRD.md](01_PRD.md) | What we are building and why | Problem, user, goals, non-goals, learner journey, feature specification with priorities, success criteria, product risks, open questions |
| [02_ARCHITECTURE.md](02_ARCHITECTURE.md) | How the system is shaped | System diagram, components and responsibilities, provider strategy and limits, data stores, resource and latency budgets, state machines |
| [03_CONTENT_SPEC.md](03_CONTENT_SPEC.md) | The content system | All four JSON schemas, validation rules, content loading behavior, source-book pipeline, benchmark reconciliation, licensing |
| [04_ENGINEERING_RULES.md](04_ENGINEERING_RULES.md) | How we write and operate code | Code quality, testing, naming, errors, logging, config, security, performance, docs standards, AI-agent coding rules, backup/ops |
| [05_IMPLEMENTATION_PLAN.md](05_IMPLEMENTATION_PLAN.md) | The build sequence | Machine setup, repository layout, phases with hard gates, content sessions, skills checklist, effort estimates |
| [06_TASK_QUEUE.md](06_TASK_QUEUE.md) | Atomic work items | Task IDs, goals, files, dependencies, acceptance criteria, tests |
| [07_PROMPTS.md](07_PROMPTS.md) | The three personas | Prompt design rules, persona specs, context assembly, regression requirements |
| [08_ARCHITECTURE_DECISIONS.md](08_ARCHITECTURE_DECISIONS.md) | The "why" record | ADR-1 through ADR-9 plus the decisions log convention |

A separate REVIEW_REPORT.md (repo root, not docs/) lists known gaps, ambiguities, and inconsistencies found during documentation review. Consult it before starting any task it names.

## Quick facts

- One user, one machine. No auth, no multi-tenancy, no production traffic.
- Zero recurring cost target: free API tiers within their limits, offline fallback.
- Content (cases, guesstimates, lessons, benchmarks) is data on disk, never code. See [03_CONTENT_SPEC.md](03_CONTENT_SPEC.md).
- The LLM roleplays and teaches from content files; it never invents facts mid-session (ADR-1).
- The backend owns all state; the model is stateless per call (ADR-2).
- Arithmetic is verified in Python, never by the LLM (ADR-3).

## Glossary

- **Case**: a full interview case with phases, exhibits, and a rubric.
- **Guesstimate**: a standalone estimation question with an approach tree.
- **Lesson**: a teachable unit with sections and a quiz.
- **Benchmarks**: the single canonical facts file (`benchmarks.json`) all content references.
- **Mode**: guided | standard | cold (cases); coached | timed (guesstimates).
- **Ladder**: the per-topic learn → drill → perform progression (PRD 1.6).
- **Provider router**: the failover chain Groq → Nvidia → Ollama (ADR-5).
- **C-session**: a content conversion session done with Claude outside the codebase (ADR-8).
- **Persona**: one of interviewer, coach, tutor ([07_PROMPTS.md](07_PROMPTS.md)).
