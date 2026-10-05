# Telemetry — local capture + Azure export

Captures the research agent's OpenTelemetry output to local JSONL files and
forwards it to Azure Application Insights, which routes it into the
`AppTraces` / `AppMetrics` / `AppDependencies` tables of the
`law-proptimise-platform` Log Analytics workspace. No Docker.

**The collector does not read `.env` itself** — it is a separate process.
`run_collector.ps1` loads `.env` into its own environment before launching,
and refuses to start if `APPLICATIONINSIGHTS_CONNECTION_STRING` is missing.

## Components

| Piece | Path | Role |
|---|---|---|
| Collector binary | `%USERPROFILE%\Downloads\otelcol-contrib.exe` (v0.158.0) | Receives OTLP, writes to disk |
| Collector config | `otel/collector-config.yaml` | Receivers → processors → exporters |
| Launch script | `otel/run_collector.ps1` | Starts the collector |
| Inspector | `otel/inspect_telemetry.py` | Summarizes captured signals |
| Captured data | `telemetry/{traces,metrics,logs}.jsonl` | One OTLP JSON batch per line |

## How the agent emits telemetry

The Agent SDK runs Claude Code as a subprocess, and *that process* is the OTLP
producer. `research_agent.py:telemetry_env()` builds the env vars and passes
them through `ClaudeAgentOptions(env=...)`. Traces need the beta flag
(`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`) on top of `OTEL_TRACES_EXPORTER`.

Export intervals are shortened (metrics 5s, logs/traces 2s) because the default
60s metric interval is longer than a typical agent run.

## Running it

Terminal 1 — collector:

```powershell
.\otel\run_collector.ps1
```

Terminal 2 — agent:

```powershell
.venv\Scripts\python research_agent.py "your topic here"
```

Then inspect what was captured:

```powershell
.venv\Scripts\python otel\inspect_telemetry.py
```

Set `AGENT_TELEMETRY_ENABLED=0` to run the agent without emitting telemetry.

## Verified captured signals

A single run produces:

**Metrics** — `claude_code.session.count`, `claude_code.token.usage`
(input/output/cacheRead/cacheCreation), `claude_code.cost.usage`,
`claude_code.active_time.total`, `claude_code.lines_of_code.count`,
`claude_code.code_edit_tool.decision`.

**Log events** — `user_prompt`, `api_request`, `assistant_response`,
`tool_decision`, `tool_result`, `skill_activated`, `plugin_loaded`,
`mcp_server_connection`, `managed_settings_resolved`.

**Spans** — `claude_code.interaction` (root), `claude_code.llm_request`,
`claude_code.tool`, `claude_code.tool.execution`,
`claude_code.tool.blocked_on_user`, parented into a single trace per run.

Cost and token metrics carry a `skill.name` attribute, so spend is attributable
to `web-research` vs `report-writing` per run.

## Azure export

The `azuremonitor` exporter sends to Application Insights, which writes into the
workspace tables:

| Signal | Table | Keyed by |
|---|---|---|
| Spans | `AppDependencies` | `Name`, `DependencyType=InProc`, `OperationId`/`ParentId` |
| Metrics | `AppMetrics` | `Name` (e.g. `claude_code.cost.usage`) |
| Log events | `AppTraces` | `Message` (e.g. `claude_code.tool_result`) |

`service.name` becomes `AppRoleName`, which is how this workspace already
separates `claude-code`, `proptimise-backend` and `proptimise-worker`. Ours is
`research-agent`.

Verification queries are in `docs/phase2b-requirements.md` §6.


## Troubleshooting: nothing appears in Azure

Run the direct ingestion test first. It bypasses the collector and answers
whether Azure accepts our credential:

```powershell
.venv\Scripts\python otel	est_azure_connection.py
```

| Result | Meaning | Fix |
|---|---|---|
| `PASS` | Azure accepted the item | Data is flowing; wait 2-5 min, then check the query (see below) |
| `could not reach the endpoint` / timeout | Network egress to the ingestion endpoint is blocked | Firewall/proxy change - see below |
| HTTP 401 / 403 | Local auth disabled on the resource | Entra ID required; needs `azureauthextension` |
| HTTP 400 | Instrumentation key invalid for that endpoint | Wrong connection string |

### Egress is blocked (observed 2026-09-23)

`*.in.applicationinsights.azure.com` and `dc.services.visualstudio.com` time
out on TCP 443, while `api.loganalytics.io`, `management.azure.com`,
`portal.azure.com` and `login.microsoftonline.com` all connect. The blocked and
allowed hosts share a `/24` (`20.9.155.0/24`), so this is a hostname-based
firewall rule, not IP filtering.

The effect is that the workspace can be **queried** but not **written to** -
which looks exactly like "the exporter is broken" but is not.

If a proxy is available, set `HTTPS_PROXY` in `.env`; `run_collector.ps1` loads
it into the collector's environment.

### The query returns nothing but the test PASSED

Check what role name actually arrived, rather than filtering by a guess:

```kusto
union isfuzzy=true AppTraces, AppMetrics, AppDependencies
| where TimeGenerated > ago(1h)
| summarize count() by Type, AppRoleName
```

`service.name` becomes `AppRoleName`, so ours should appear as `research-agent`
alongside the existing `claude-code`.
