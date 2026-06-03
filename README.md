# 🏛️ Agentic Architects

A multi-agent AI system where **five specialized architect agents**, each powered
by Claude, collaborate to turn a plain-English project brief into a complete,
coherent software architecture.

| Agent | Owns |
| --- | --- |
| 🧭 **Solution Architect** | Overall design, integration, trade-offs, and final synthesis (leads the team) |
| 🗄️ **Data Architect** | Data models, storage, pipelines, governance, lifecycle |
| 🛡️ **Security Architect** | Threat model, identity, data protection, compliance |
| 📈 **Observability Architect** | Logging, metrics, tracing, SLOs, incident readiness |
| ☁️ **Cloud Architect** | Infrastructure, networking, scaling, IaC, cost |

## How it works

The agents run as a coordinated **workflow**, not a free-for-all:

```
            ┌─────────────────────────────────────────────┐
  brief ──▶ │ 1. Solution Architect drafts high-level design│
            └───────────────────────┬─────────────────────┘
                                    │  (brief + high-level design)
              ┌─────────────┬───────┴───────┬──────────────┐
              ▼             ▼               ▼              ▼
          🗄️ Data      🛡️ Security   📈 Observability   ☁️ Cloud     ← run in parallel
              └─────────────┴───────┬───────┴──────────────┘
                                    ▼
            ┌─────────────────────────────────────────────┐
            │ 3. Solution Architect synthesizes everything │ ──▶ Markdown report
            │    into one document + decision log + risks  │
            └─────────────────────────────────────────────┘
```

1. The **Solution Architect** reads the brief and produces a high-level design.
2. The four **domain specialists** each deep-dive their area *in parallel*,
   building on that shared design.
3. The **Solution Architect** reconciles the four sections into a single
   architecture document with an executive summary, a numbered decision log,
   open risks, and a delivery roadmap.

### Built on the Claude API

- Uses the official `anthropic` Python SDK and **Claude Opus 4.8** by default.
- **Adaptive thinking** + tunable `effort` so each agent reasons as deeply as the
  brief warrants.
- **Streaming** for the long architecture write-ups (keeps requests under the
  SDK timeout).
- **Prompt caching**: the brief + high-level design are placed in a cached system
  block shared byte-for-byte across the four parallel specialists, so the shared
  context is read from cache instead of re-billed four times. The CLI prints how
  many cached tokens were reused.

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure your API key
cp .env.example .env        # then edit .env and add your key
#   or: export ANTHROPIC_API_KEY=sk-ant-...

# 3. Run it
python -m architects "Design a multi-tenant SaaS for real-time product analytics."
```

### More ways to run

```bash
# From a brief file, writing the report to disk
python -m architects --brief-file examples/brief-analytics-saas.md -o output/review.md

# Pipe a brief in on stdin
echo "Design a URL shortener that handles 100k redirects/sec" | python -m architects

# Tune depth vs. cost/latency (low | medium | high | xhigh | max)
python -m architects --effort xhigh --brief-file examples/brief-analytics-saas.md
```

## Configuration

| Setting | Env var | Default | Notes |
| --- | --- | --- | --- |
| API key | `ANTHROPIC_API_KEY` | — | Required. |
| Model | `ARCHITECT_MODEL` | `claude-opus-4-8` | Any current Claude model. |
| Effort | `ARCHITECT_EFFORT` | `high` | `low`→`max`; higher = deeper reasoning, more tokens. |

CLI flags (`--model`, `--effort`) override the environment.

## Use it as a library

```python
import asyncio
from architects import run_review
from architects.report import render_markdown

async def main():
    review = await run_review("Design a real-time chat backend for 1M users.")
    print(render_markdown(review))
    # review.high_level_design, review.sections["security"], review.final_document, ...

asyncio.run(main())
```

## Project layout

```
architects/
  agents.py         # the 5 architect personas (system prompts)
  config.py         # model/effort settings + client construction
  orchestrator.py   # the 3-phase coordination workflow
  report.py         # ArchitectureReview -> Markdown
  cli.py            # command-line interface
examples/           # sample briefs
tests/              # offline tests (no API key / network needed)
```

## Tests

```bash
python tests/test_offline.py     # or: python -m pytest
```

The offline tests cover agent wiring, config validation, and report rendering —
no API key or network required.

## Notes

- The Security Architect produces **defensive** security guidance (threat models,
  controls, compliance) for systems you are authorized to build.
- The system makes a separate Claude call per agent (6 total per run: 1 draft +
  4 specialists + 1 synthesis). Use a lower `--effort` for cheaper, faster runs.
