"""Summarize the JSONL telemetry captured by the collector.

Usage:  python otel/inspect_telemetry.py [telemetry_dir]
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

TELEMETRY_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "telemetry")


def records(name):
    path = TELEMETRY_DIR / name
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def attr_value(v):
    """Unwrap an OTLP AnyValue ({'stringValue': 'x'} -> 'x')."""
    if not isinstance(v, dict) or not v:
        return None
    key, val = next(iter(v.items()))
    if key == "arrayValue":
        return [attr_value(i) for i in val.get("values", [])]
    return val


def attrs(obj):
    return {a["key"]: attr_value(a["value"]) for a in obj.get("attributes", [])}


def datapoint_value(dp):
    if "asInt" in dp:
        return int(dp["asInt"])
    if "asDouble" in dp:
        return float(dp["asDouble"])
    return None


def main():
    print(f"telemetry dir: {TELEMETRY_DIR}\n")

    # ---- metrics -----------------------------------------------------------
    totals = defaultdict(float)
    tokens_by_type = defaultdict(float)
    cost_by_skill = defaultdict(float)
    for r in records("metrics.jsonl"):
        for rm in r.get("resourceMetrics", []):
            for sm in rm.get("scopeMetrics", []):
                for m in sm.get("metrics", []):
                    points = m.get("sum", {}).get("dataPoints") or m.get("gauge", {}).get("dataPoints") or []
                    for dp in points:
                        val = datapoint_value(dp)
                        if val is None:
                            continue
                        a = attrs(dp)
                        totals[m["name"]] += val
                        if m["name"] == "claude_code.token.usage":
                            tokens_by_type[a.get("type", "?")] += val
                        if m["name"] == "claude_code.cost.usage":
                            cost_by_skill[a.get("skill.name", "(no skill)")] += val

    print("METRICS")
    for name in sorted(totals):
        print(f"  {name:<40} {totals[name]:,.4f}")
    if tokens_by_type:
        print("  tokens by type:", {k: int(v) for k, v in sorted(tokens_by_type.items())})
    if cost_by_skill:
        print("  cost by skill :", {k: round(v, 4) for k, v in sorted(cost_by_skill.items())})

    # ---- logs --------------------------------------------------------------
    events = Counter()
    skills = []
    tools = Counter()
    for r in records("logs.jsonl"):
        for rl in r.get("resourceLogs", []):
            for sl in rl.get("scopeLogs", []):
                for lr in sl.get("logRecords", []):
                    a = attrs(lr)
                    name = a.get("event.name") or lr.get("eventName", "?")
                    events[name] += 1
                    if name == "skill_activated":
                        skills.append(a.get("skill.name"))
                    if name == "tool_result":
                        tools[f"{a.get('tool_name')} ({'ok' if a.get('success') == 'true' else 'fail'})"] += 1

    print("\nLOG EVENTS")
    for name, count in sorted(events.items()):
        print(f"  {name:<40} x{count}")
    if skills:
        print(f"  skills activated: {skills}")
    if tools:
        print(f"  tool results    : {dict(tools)}")

    # ---- traces ------------------------------------------------------------
    spans = Counter()
    traces = set()
    durations = defaultdict(list)
    for r in records("traces.jsonl"):
        for rs in r.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for s in ss.get("spans", []):
                    spans[s["name"]] += 1
                    traces.add(s["traceId"])
                    ms = (int(s["endTimeUnixNano"]) - int(s["startTimeUnixNano"])) / 1e6
                    durations[s["name"]].append(ms)

    print("\nSPANS")
    for name in sorted(spans):
        d = durations[name]
        print(f"  {name:<40} x{spans[name]:<4} total={sum(d)/1000:>7.1f}s  max={max(d)/1000:>6.1f}s")
    print(f"  distinct traces : {len(traces)}")


if __name__ == "__main__":
    main()
