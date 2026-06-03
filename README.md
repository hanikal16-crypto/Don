# 🏛️ Agentic Architects

Give a **spec** in. Get a **designed and built end-to-end solution** out.

A multi-agent system where a team of Claude-powered agents **design** a software
system and then **autonomously build** it into a runnable repository — frontend,
backend, tests, and CI. The engineers don't just emit code: they work in a real
workspace with tools (`write_file`, `read_file`, `list_dir`, `run_command`),
**run their code, run the tests, and fix failures themselves** in an agentic
loop. It ships as a **web app** (frontend + backend) so you can paste a spec,
watch the agents work live (every tool call streamed), and download the repo.

## The team

**Architects — design the system (5 agents):**

| Agent | Owns |
| --- | --- |
| 🧭 Solution Architect | Overall design, integration, trade-offs, final synthesis (leads) |
| 🗄️ Data Architect | Data models, storage, pipelines, governance |
| 🛡️ Security Architect | Threat model, identity, data protection, compliance |
| 📈 Observability Architect | Logging, metrics, tracing, SLOs |
| ☁️ Cloud Architect | Infrastructure, networking, scaling, IaC, cost |

**Engineers — build the solution (4 agents):**

| Agent | Owns |
| --- | --- |
| 🛠️ Tech Lead | Chooses the stack and plans the file-by-file build |
| ⚙️ Backend Engineer | Implements the backend API, data layer, business logic |
| 🎨 Frontend Engineer | Implements the frontend UI and its API client |
| 🧪 QA Engineer | Writes automated tests and the CI pipeline |

## How it works

```
 spec ──▶ ┌─ DESIGN ──────────────────────────────────────────────┐
          │ Solution Architect drafts the high-level design         │
          │   └▶ Data · Security · Observability · Cloud (parallel) │
          │   └▶ Solution Architect synthesizes the architecture    │
          └────────────────────────────┬──────────────────────────┘
                                        │ (architecture)
          ┌─ BUILD (autonomous agents in a shared workspace) ──────┐
          │ Tech Lead plans the repo (stack + file manifest)       │
          │   └▶ Backend engineer: writes files, installs, runs    │
          │   └▶ Frontend engineer: builds against the real API    │
          │   └▶ QA engineer: writes tests, RUNS them, fixes until │
          │      green — each driving its own tool-use loop        │
          └────────────────────────────┬──────────────────────────┘
                                        ▼
                 a runnable repo  +  architecture doc  (download as .zip)
```

Both layers of this project have a **frontend and a backend**:

1. **The platform** — a FastAPI backend + a no-build web UI you interact with.
2. **The generated output** — a full repo (frontend + backend + tests + CI) for
   the system described in your spec.

### Built on the Claude API

- Official `anthropic` SDK with **Claude Opus 4.8**, **adaptive thinking**, and
  tunable `effort`.
- **Streaming** everywhere (architecture write-ups and large code files).
- **Agentic tool-use loop** (the "agent" tier): each engineer runs a manual
  loop with client-side tools and self-verifies by actually running its code.
- **Structured outputs** (`output_config.format` + Pydantic) for the Tech Lead's
  build plan.
- **Prompt caching**: the shared spec/design/plan is placed in a cached system
  block reused byte-for-byte across the parallel agents, so it is read from
  cache instead of re-billed per agent. Cache reuse is reported in the UI/CLI.
- Generated file paths are **path-traversal-guarded** before they are written or
  zipped.

## Run the web app

```bash
pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY
uvicorn server.app:app --reload
# open http://127.0.0.1:8000
```

Paste a spec, choose whether to generate the full repo, pick an effort level,
and hit **Run the team**. Watch each agent's status update live, read the
architecture and solution overview, browse the generated file list, and download
the repo as a `.zip`.

> The run store is in-memory, so run a **single** uvicorn worker. For
> multi-worker/horizontal scaling, move the store + event bus to Redis.

## Run from the command line

```bash
# Design + build a full e2e repo into ./output/solution/
python -m architects "Design a multi-tenant SaaS for real-time product analytics."

# Use a spec file; choose where the repo and the architecture doc go
python -m architects --brief-file examples/brief-analytics-saas.md \
    --out-dir build/analytics --report build/architecture.md

# Design only, no code generation
python -m architects --no-build --brief-file examples/brief-analytics-saas.md

# Tune reasoning depth vs. cost/latency
python -m architects --effort xhigh --brief-file examples/brief-analytics-saas.md
```

## Use it as a library

```python
import asyncio
from architects import run_pipeline
from architects.codegen import write_solution

async def main():
    result = await run_pipeline("Design a real-time chat backend for 1M users.")
    print(result.review.final_document)        # the architecture
    if result.solution:                        # the generated repo
        write_solution(result.solution.files, "output/chat")

asyncio.run(main())
```

`run_review(spec)` is a design-only shortcut that returns just the
`ArchitectureReview`.

## Configuration

| Setting | Env var | Default | Notes |
| --- | --- | --- | --- |
| API key | `ANTHROPIC_API_KEY` | — | Required for real runs. |
| Model | `ARCHITECT_MODEL` | `claude-opus-4-8` | Any current Claude model. |
| Effort | `ARCHITECT_EFFORT` | `high` | `low`→`max`; deeper = more tokens. |
| Code-gen tokens | `ARCHITECT_ENGINEERING_MAX_TOKENS` | `48000` | Output ceiling per agent turn. |
| Max steps | `ARCHITECT_MAX_STEPS` | `40` | Tool-call budget per engineer (loop cap). |
| Bash timeout | `ARCHITECT_BASH_TIMEOUT` | `180` | Per-command timeout (seconds). |
| Disable bash | `ARCHITECT_DISABLE_BASH` | unset | Set to `1` to forbid `run_command`. |

## Project layout

```
architects/            the agent pipeline (a library + CLI)
  agents.py            the 9 agent personas (architects + engineers)
  config.py            model/effort/token settings + client
  llm.py               streamed text + structured Claude calls
  tools.py             workspace + client-side tools (write/read/list/run)
  agent_loop.py        the autonomous agentic loop (manual tool-use loop)
  codegen.py           file models, path safety, write/zip
  orchestrator.py      the design + autonomous engineering workflow
  report.py            ArchitectureReview/solution -> Markdown
  events.py            progress event model
  cli.py               `python -m architects`
server/                the platform web app
  app.py               FastAPI backend (runs, SSE, downloads)
  runstore.py          in-memory runs + replayable event streams
  static/              no-build SPA (index.html, app.js, styles.css)
examples/              sample specs
tests/                 offline tests (no API key / network needed)
```

## Tests

```bash
python tests/run_all.py        # or: python -m pytest
```

Covers agent wiring, config validation, report rendering, code-gen models +
path-traversal guard, and the FastAPI routes/SSE flow (with a faked pipeline —
no API key or network required).

## Security ⚠️

The engineering agents run **arbitrary shell commands** via `run_command`
(installing dependencies, running tests, etc.) — that autonomy is the whole
point, but it means generated/agent-chosen commands execute with the host's
privileges. **Run the platform in a disposable container** (this is also the
default posture of the hosted environment). Commands are confined to the run's
workspace directory and time-limited, and file tools are path-traversal-guarded,
but that is not a substitute for OS-level isolation. Set
`ARCHITECT_DISABLE_BASH=1` to let agents read/write files without executing
anything.

## Notes & limits

- A full run is the 6 design calls **plus an autonomous build loop** per
  engineer (many tool-use turns each, bounded by `ARCHITECT_MAX_STEPS`), so it
  is the most capable *and* the most token-heavy mode. Use `--no-build` or a
  lower `--effort` for cheaper, faster runs.
- The agents self-verify (run the tests and fix failures), but success is not
  guaranteed for an arbitrary spec — the generated CI lets you confirm
  downstream.
- The Security Architect produces **defensive** guidance for systems you are
  authorized to build.
