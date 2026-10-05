"""Send one synthetic telemetry item straight to Application Insights.

Bypasses the collector entirely, so it answers one question: does Azure accept
our connection string?

    python otel/test_azure_connection.py

Exit code 0 means Azure accepted the item. Uses only the standard library.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env_file() -> dict[str, str]:
    env_path = PROJECT_ROOT / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def parse_connection_string(conn: str) -> dict[str, str]:
    parts = {}
    for chunk in conn.split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parts[key.strip().lower()] = value.strip()
    return parts


def main() -> int:
    env = load_env_file()
    conn = env.get("APPLICATIONINSIGHTS_CONNECTION_STRING") or os.getenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING", ""
    )
    if not conn:
        print("FAIL: APPLICATIONINSIGHTS_CONNECTION_STRING not found in .env or environment")
        return 2

    parts = parse_connection_string(conn)
    ikey = parts.get("instrumentationkey")
    endpoint = parts.get("ingestionendpoint")

    if not ikey:
        print("FAIL: connection string has no InstrumentationKey")
        return 2
    if not endpoint:
        print("FAIL: connection string has no IngestionEndpoint")
        print("      Without it the exporter falls back to the legacy global endpoint,")
        print("      which may not route to your workspace.")
        return 2

    url = endpoint.rstrip("/") + "/v2.1/track"
    print(f"IKey     : {ikey}")
    print(f"Endpoint : {url}")

    payload = {
        "name": "Microsoft.ApplicationInsights.Message",
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "iKey": ikey,
        "tags": {"ai.cloud.role": "research-agent", "ai.cloud.roleInstance": "connectivity-test"},
        "data": {
            "baseType": "MessageData",
            "baseData": {
                "ver": 2,
                "message": "AgentTelemetry connectivity test",
                "severityLevel": 1,
                "properties": {"source": "test_azure_connection.py"},
            },
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps([payload]).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        status = err.code
        body = err.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as err:
        print(f"\nFAIL: could not reach the endpoint - {err.reason}")
        print("      Check outbound HTTPS/443 and any corporate proxy (HTTPS_PROXY).")
        return 1

    print(f"HTTP     : {status}")
    print(f"Response : {body}")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = {}

    accepted = parsed.get("itemsAccepted")
    if status == 200 and accepted:
        print("\nPASS: Azure accepted the item.")
        print("Now query the workspace (allow 2-5 min):")
        print('  AppTraces | where AppRoleName == "research-agent" | where TimeGenerated > ago(30m)')
        print("\nIf that returns nothing but this passed, the App Insights resource is")
        print("not connected to the workspace you are querying (see notes below).")
        return 0

    print("\nFAIL: Azure did not accept the item.")
    for error in parsed.get("errors", []):
        print(f"  - {error}")
    if status == 401 or status == 403:
        print("  Local auth is probably disabled on the resource (Entra ID required).")
    if status == 400:
        print("  The instrumentation key is likely invalid for this endpoint.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
