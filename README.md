# AgentTelemetry

A web research agent built on the **Claude Agent SDK** that searches the web on a
given topic and writes a cited Markdown report — instrumented end-to-end with
**OpenTelemetry**.

```
python research_agent.py "Effect of instagram reels on the human brain"
  -> reports/effect-of-instagram-reels-on-the-human-brain-20260922-080724.md
  -> traces, metrics and logs captured by a local OTel Collector
```

## Project status

| Phase | Scope | Status |
|---|---|---|
| 1 | Research agent (Agent SDK, two skills, Markdown report) | Done |
| 2a | OTel Collector capturing telemetry locally to disk | Done |
| 2b | Forward telemetry to Azure Application Insights / Log Analytics | Done |

---

## Project structure

```
AgentTelemetry/
├── research_agent.py              # the agent — entry point
├── prompts/
│   └── system_prompt.md           # the agent's system prompt
├── .claude/skills/                # skills, discovered from disk by the SDK
│   ├── web-research/SKILL.md      #   phase 1: how to gather evidence
│   └── report-writing/SKILL.md    #   phase 2: how to write the report
├── otel/
│   ├── collector-config.yaml      # Collector pipeline definition
│   ├── run_collector.ps1          # starts the Collector
│   ├── inspect_telemetry.py       # summarizes what was captured
│   └── README.md                  # telemetry runbook
├── reports/                       # generated reports (git-ignored)
├── telemetry/                     # captured signals as JSONL (git-ignored)
├── references/                    # original source notes the skills were built from
├── requirements.txt
├── .env.example                   # copy to .env to override settings
└── .gitignore
```

### What each file does

| File | Purpose |
|---|---|
| `research_agent.py` | Builds `ClaudeAgentOptions`, runs `query()`, streams progress, resolves the output file. ~200 lines, read top-to-bottom. |
| `prompts/system_prompt.md` | Defines the agent's role and the two-phase workflow (research, then write). Loaded at import. |
| `.claude/skills/web-research/SKILL.md` | Search strategy, source-priority ladder, citation rules, and a **research budget** (3–5 searches) that keeps cost down. |
| `.claude/skills/report-writing/SKILL.md` | Report structure (Executive Summary → Key Findings → Analysis → Risks → Sources), formatting rules, and the instruction to `Write` to the given path. |
| `otel/collector-config.yaml` | OTLP receivers → processors → file + console exporters. |
| `otel/run_collector.ps1` | Launches the Collector against that config. |
| `otel/inspect_telemetry.py` | Reads `telemetry/*.jsonl` and prints a summary of metrics, events and spans. |

---

## Architecture

The single most important thing to understand: **the Python process is not what
talks to Claude, and not what emits telemetry.** The Agent SDK launches Claude
Code as a subprocess, and that subprocess does the model calls, the web searches,
the file writes, *and* the OTLP export.

```
┌─────────────────────┐
│  research_agent.py  │  builds options + prompt, streams messages
│  (Python, your code)│
└──────────┬──────────┘
           │ Agent SDK query()  — options.env carries the OTEL_* vars
           ▼
┌─────────────────────┐        WebSearch / WebFetch
│   Claude Code       │ ─────────────────────────────►  the web
│   (subprocess)      │
│                     │        Write  ──────────────►  reports/*.md
│   model: sonnet     │
└──────────┬──────────┘
           │ OTLP / HTTP  →  127.0.0.1:4318
           ▼
┌─────────────────────┐
│  OTel Collector     │  receivers → memory_limiter → resource → batch
│  (otelcol-contrib)  │
└──────────┬──────────┘
           ├──────────────► console (debug exporter, verbosity: normal)
           ├──────────────► telemetry/{traces,metrics,logs}.jsonl   (local tee)
           └──────────────► Azure Application Insights
                              ├─ spans   → AppDependencies
                              ├─ metrics → AppMetrics
                              └─ logs    → AppTraces
```

**Why telemetry is just environment variables.** Because Claude Code is the OTLP
producer, enabling telemetry means handing it the right `OTEL_*` variables via
`ClaudeAgentOptions(env=...)`. There is no `opentelemetry-sdk` dependency on the
Python side. See `telemetry_env()` in `research_agent.py`.

**How the skills are found.** Skills are filesystem artifacts, not objects you
register in code. The SDK discovers `.claude/skills/*/SKILL.md` under `cwd` when
`setting_sources` includes `"project"`. The `skills=[...]` list then restricts
which of the discovered skills the model may invoke, and `"Skill"` must be in the
tool list.

**Agent run flow.** One run is a single trace:

1. The prompt tells the model to invoke `web-research`, then `report-writing`.
2. Research phase — 3–5 `WebSearch` calls, occasionally a `WebFetch`.
3. Writing phase — one `Write` call containing the whole report.
4. `locate_report()` confirms the file exists. If the model mistyped the path
   into its `Write` call (it happens with long filenames), the file it actually
   wrote is renamed into place rather than a second file being produced.

---

## Setup

Requires Python 3.13 and a working `claude` CLI login (or an API key).

```powershell
# from the project root, with .venv already created
.venv\Scripts\python -m pip install -r requirements.txt
```

The OpenTelemetry Collector is a **standalone binary**, not a pip package.
This project was verified against `otelcol-contrib` **v0.158.0** at
`%USERPROFILE%\Downloads\otelcol-contrib.exe`. Override with `OTELCOL_PATH`.

**Authentication** — the SDK picks up an existing `claude` CLI login
automatically (`claude auth status` to check). Alternatively copy
`.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

---

## Running the agent

```powershell
.venv\Scripts\python research_agent.py "How do LLMs work, their internals in detail"
```

With an explicit output path:

```powershell
.venv\Scripts\python research_agent.py "Q1 2026 financial report of Apple Inc" -o reports/apple-q1.md
```

Progress streams as it runs — skill invocations, each search query, the file
write — ending with turn count, duration and cost. A typical run is
**~10–11 turns, ~70–80 s, ~$0.21–0.25**.

If the Collector is not running the agent still works; telemetry export fails
silently in the background. To skip telemetry entirely, set
`AGENT_TELEMETRY_ENABLED=0`.

---

## Capturing telemetry

Start the Collector **first**, in its own terminal:

```powershell
.\otel\run_collector.ps1
```

It listens on `127.0.0.1:4317` (gRPC) and `127.0.0.1:4318` (HTTP) and writes to
`telemetry/`. Then run the agent in a second terminal as above. Afterwards:

```powershell
.venv\Scripts\python otel\inspect_telemetry.py
```

```
METRICS
  claude_code.cost.usage                   0.2126
  claude_code.token.usage                  126,714.0000
  tokens by type: {'cacheCreation': 13788, 'cacheRead': 61570, 'input': 44278, 'output': 7078}
  cost by skill : {'(no skill)': 0.1027, 'report-writing': 0.0691, 'web-research': 0.0408}

LOG EVENTS
  skill_activated                          x2
  tool_result                              x8
  tool results    : {'Skill (ok)': 2, 'WebSearch (ok)': 4, 'WebFetch (fail)': 1, 'Write (ok)': 1}

SPANS
  claude_code.interaction                  x1    total=   80.1s
  claude_code.llm_request                  x11   total=   79.8s
  claude_code.tool.execution               x8    total=   50.6s
```

`telemetry/*.jsonl` holds one OTLP batch per line if you need the raw records.
Files are appended to across runs — delete them to start clean.

### What gets captured

| Signal | Contents |
|---|---|
| **Metrics** | `claude_code.session.count`, `token.usage` (input / output / cacheRead / cacheCreation), `cost.usage`, `active_time.total`, `lines_of_code.count`, `code_edit_tool.decision` |
| **Logs** | `user_prompt`, `api_request`, `assistant_response`, `tool_decision`, `tool_result`, `skill_activated`, `plugin_loaded`, `mcp_server_connection`, `managed_settings_resolved` |
| **Traces** | `claude_code.interaction` (root) → `llm_request`, `tool` → `tool.execution`, `tool.blocked_on_user` |

Cost and token metrics carry a `skill.name` attribute, so spend is attributable
to `web-research` vs `report-writing` per run. Reported cost in the telemetry
matches the agent's own reported cost exactly.

---

## Configuration

All settings are environment variables, overridable via `.env` (copy from
`.env.example`). `.env` is loaded at import, before any setting is read.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Optional; the `claude` CLI login is used otherwise |
| `RESEARCH_AGENT_MODEL` | `claude-sonnet-5` | Model to run |
| `RESEARCH_AGENT_EFFORT` | `medium` | Thinking/token effort, `low`…`max`. Lower is cheaper |
| `RESEARCH_AGENT_MAX_TURNS` | `20` | Turn ceiling for one run |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | — | **Required for Azure export.** Read by the collector, not the agent |
| `AGENT_TELEMETRY_ENABLED` | `1` | Set `0` to run without emitting telemetry |
| `OTEL_LOG_ASSISTANT_RESPONSES` | unset | Set `1` to also log full report bodies (large) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://127.0.0.1:4318` | Collector endpoint |
| `OTEL_SERVICE_NAME` | `research-agent` | `service.name` resource attribute |
| `OTELCOL_PATH` | `%USERPROFILE%\Downloads\otelcol-contrib.exe` | Collector binary |

### Cost control

Three levers, in order of impact:

1. **The research budget** in `web-research/SKILL.md` — capping searches at 3–5
   and forbidding re-searching known facts. Search results are carried through
   every subsequent turn, so this dominates cost.
2. **`RESEARCH_AGENT_EFFORT`** — `medium` rather than the `high` default.
3. **`RESEARCH_AGENT_MAX_TURNS`** — a ceiling, not a target.

---

## Dependencies

```
claude-agent-sdk==0.2.157
python-dotenv>=1.0
```

Plus the `otelcol-contrib` v0.158.0 binary (external, not pip-installable).
Everything else the project uses is in the Python standard library.
