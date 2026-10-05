# Starts the OpenTelemetry Collector (Phase 2b: local capture + Azure export).
# Usage:  .\otel\run_collector.ps1
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# The collector is a separate process and does not read .env itself, so load it
# here into this process's environment before launching.
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $name, $value = $line.Split("=", 2)
            # Strip optional surrounding quotes.
            $value = $value.Trim().Trim('"').Trim("'")
            Set-Item -Path "env:$($name.Trim())" -Value $value
        }
    }
}

# Org attribute defaults, so ${env:...} in the config always resolves.
if (-not $env:TELEMETRY_TENANT_ID) { $env:TELEMETRY_TENANT_ID = "a54b2e21-ad8b-4279-bf35-2d63bd5eedf3" }
if (-not $env:TELEMETRY_ORIGIN_COMPONENT) { $env:TELEMETRY_ORIGIN_COMPONENT = "research-agent" }
if (-not $env:TELEMETRY_AGENT_ID) { $env:TELEMETRY_AGENT_ID = "b7d4e1a2-3f65-4c08-9e71-5a2c8d4f6b93" }

$Collector = $env:OTELCOL_PATH
if (-not $Collector) { $Collector = "$env:USERPROFILE\Downloads\otelcol-contrib.exe" }
if (-not (Test-Path $Collector)) {
    Write-Error "Collector not found at $Collector. Set OTELCOL_PATH to override."
}

$Conn = $env:APPLICATIONINSIGHTS_CONNECTION_STRING
if (-not $Conn) {
    Write-Error "APPLICATIONINSIGHTS_CONNECTION_STRING is not set. Add it to .env (see .env.example)."
}
if ($Conn -notmatch "InstrumentationKey=") {
    Write-Error "APPLICATIONINSIGHTS_CONNECTION_STRING does not look like a connection string (no InstrumentationKey=)."
}

# Show only the instrumentation key, never the whole secret.
$IKey = [regex]::Match($Conn, "InstrumentationKey=([^;]+)").Groups[1].Value

New-Item -ItemType Directory -Force -Path "$ProjectRoot\telemetry" | Out-Null

Write-Host "Collector : $Collector"
Write-Host "Config    : otel\collector-config.yaml"
Write-Host "Listening : 127.0.0.1:4317 (gRPC) / 127.0.0.1:4318 (HTTP)"
Write-Host "Local tee : telemetry\{traces,metrics,logs}.jsonl"
Write-Host "Azure     : App Insights IKey $IKey"
Write-Host "tenantId  : $env:TELEMETRY_TENANT_ID"
Write-Host "component : $env:TELEMETRY_ORIGIN_COMPONENT"
Write-Host "Ctrl+C to stop.`n"

& $Collector --config "$ProjectRoot\otel\collector-config.yaml"
