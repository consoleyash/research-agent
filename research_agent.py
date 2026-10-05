"""Web research agent built on the Claude Agent SDK.

Researches a topic on the web and writes a Markdown report.

    python research_agent.py "Effect of instagram reels on the human brain"
    python research_agent.py "Q1 2026 financials of Apple Inc" -o reports/apple.md

The agent runs on Claude Sonnet and uses two project skills that live in
.claude/skills/ : `web-research` (how to gather evidence) and `report-writing`
(how to write the report). OpenTelemetry is emitted to a local collector.
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

PROJECT_ROOT = Path(__file__).resolve().parent

# Load .env before anything reads os.getenv, so settings below can be overridden.
load_dotenv(PROJECT_ROOT / ".env")

# --- Configuration ----------------------------------------------------------

MODEL = os.getenv("RESEARCH_AGENT_MODEL", "claude-sonnet-5")
EFFORT = os.getenv("RESEARCH_AGENT_EFFORT", "medium")  # low..max; lower is cheaper
MAX_TURNS = int(os.getenv("RESEARCH_AGENT_MAX_TURNS", "20"))

SKILLS = ["web-research", "report-writing"]
TOOLS = ["WebSearch", "WebFetch", "Write", "Skill"]

SYSTEM_PROMPT = (PROJECT_ROOT / "prompts" / "system_prompt.md").read_text(encoding="utf-8")


def telemetry_env() -> dict[str, str]:
    """Env vars that turn on OpenTelemetry in the Claude Code subprocess.

    The Agent SDK runs Claude Code as a subprocess and *that* process is the
    OTLP producer, so enabling telemetry is purely a matter of environment.
    Set AGENT_TELEMETRY_ENABLED=0 to run without it.
    """
    if os.getenv("AGENT_TELEMETRY_ENABLED", "1") == "0":
        return {}

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    service = os.getenv("OTEL_SERVICE_NAME", "research-agent")
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",  # spans are still beta
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        # A run lasts ~80s, so the 60s metric default can miss a run entirely.
        # 15s is frequent enough to always capture one, without the 5s debug rate.
        "OTEL_METRIC_EXPORT_INTERVAL": "15000",
        "OTEL_LOGS_EXPORT_INTERVAL": "5000",
        "OTEL_TRACES_EXPORT_INTERVAL": "5000",
        # Content logging: prompts and tool calls are recorded, not redacted.
        "OTEL_LOG_USER_PROMPTS": "1",  # the research topic, in full
        "OTEL_LOG_TOOL_DETAILS": "1",  # tool arguments: search queries, paths
        # Assistant responses stay off: they are whole report bodies, already
        # saved as .md. Set OTEL_LOG_ASSISTANT_RESPONSES=1 in .env to include.
        **(
            {"OTEL_LOG_ASSISTANT_RESPONSES": "1"}
            if os.getenv("OTEL_LOG_ASSISTANT_RESPONSES") == "1"
            else {}
        ),
        # service.name becomes AppRoleName in Application Insights.
        "OTEL_RESOURCE_ATTRIBUTES": f"service.name={service},agent.kind=web-research",
    }


# --- Agent ------------------------------------------------------------------


def default_output_path(topic: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60].rstrip("-")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / "reports" / f"{slug or 'report'}-{stamp}.md"


def build_prompt(topic: str, output_file: Path) -> str:
    return (
        f"Research topic: {topic}\n\n"
        f"Today's date is {datetime.now():%Y-%m-%d}.\n\n"
        "1. Invoke the `web-research` skill and follow it to gather evidence "
        "from the web. Keep the research phase tight: roughly 3-5 WebSearch "
        "calls and at most 2 WebFetch calls. Stop once you can answer the "
        "question with cited sources.\n"
        "2. Invoke the `report-writing` skill and write the report with the "
        "Write tool, using exactly this file_path (copy it verbatim):\n"
        f"{output_file.as_posix()}\n\n"
        "Finish with a two-sentence summary. Do not paste the report into your reply."
    )


# Which input field to show in the progress line, per tool.
TOOL_DETAIL = {"WebSearch": "query", "WebFetch": "url", "Skill": "skill", "Write": "file_path"}


async def run_agent(topic: str, output_file: Path) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    otel = telemetry_env()

    print(f"Topic     : {topic}")
    print(f"Model     : {MODEL} (effort={EFFORT}, max_turns={MAX_TURNS})")
    print(f"Output    : {output_file}")
    print(f"Telemetry : {otel.get('OTEL_EXPORTER_OTLP_ENDPOINT', 'disabled')}")

    options = ClaudeAgentOptions(
        model=MODEL,
        effort=EFFORT,
        system_prompt=SYSTEM_PROMPT,
        cwd=PROJECT_ROOT,
        setting_sources=["project"],  # discovers .claude/skills/ under cwd
        skills=SKILLS,
        tools=TOOLS,  # restrict the tool surface
        allowed_tools=TOOLS,  # and pre-approve it, so nothing prompts
        permission_mode="acceptEdits",
        max_turns=MAX_TURNS,
        env=otel,
    )

    written: list[Path] = []
    result: ResultMessage | None = None

    async for message in query(prompt=build_prompt(topic, output_file), options=options):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            print(f"Session   : {message.data.get('session_id')}")
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    print(f"\n[assistant] {block.text.strip()}")
                elif isinstance(block, ToolUseBlock):
                    detail = (block.input or {}).get(TOOL_DETAIL.get(block.name, ""), "")
                    print(f"[tool] {block.name}: {detail}")
                    if block.name == "Write" and detail:
                        written.append(Path(detail))
        elif isinstance(message, ResultMessage):
            result = message

    if result is None:
        raise RuntimeError("Agent finished without a result message.")
    if result.is_error:
        raise RuntimeError(f"Agent error: {result.errors or result.result}")

    print("\n--- result ---")
    print(f"status    : {result.subtype} ({result.num_turns} turns, {result.duration_ms / 1000:.1f}s)")
    if result.total_cost_usd is not None:
        print(f"cost      : ${result.total_cost_usd:.4f}")

    report = locate_report(output_file, written, result)
    print(f"report    : {report}")
    return report


def locate_report(requested: Path, written: list[Path], result: ResultMessage) -> Path:
    """Return the report file the agent produced.

    The model retypes the output path into its Write call and can alter it
    (e.g. drop a character from a long slug), so trust the Write calls we saw
    on the stream over the path we asked for.
    """
    if requested.exists():
        return requested

    for path in written:
        actual = path if path.is_absolute() else PROJECT_ROOT / path
        if actual.suffix == ".md" and actual.exists():
            actual.replace(requested)
            print(f"note      : agent wrote {actual.name}; renamed to requested path")
            return requested

    print("warning   : no report file written; saving the final answer instead")
    requested.write_text(result.result or "", encoding="utf-8")
    return requested


def main() -> None:
    # Windows consoles default to cp1252; model output contains en-dashes etc.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Research a topic and write a Markdown report.")
    parser.add_argument("topic", help="Topic or question to research")
    parser.add_argument("-o", "--output", help="Output .md path (default: reports/<topic>-<timestamp>.md)")
    args = parser.parse_args()

    output = Path(args.output).resolve() if args.output else default_output_path(args.topic)
    try:
        asyncio.run(run_agent(args.topic, output))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
