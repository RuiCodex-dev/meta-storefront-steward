# Owner's 30-minute label spot check: starts the local web app, opens the page, stops the server when done.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
$srv = Start-Process -FilePath $py -ArgumentList '-m','uvicorn','steward.web.app:app','--host','127.0.0.1','--port','8765' `
       -WindowStyle Minimized -PassThru
try {
    $ok = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8765/spotcheck' -TimeoutSec 2 | Out-Null; $ok = $true; break } catch {}
    }
    if (-not $ok) { throw 'the local server did not start' }
    Start-Process 'http://127.0.0.1:8765/spotcheck'
    Write-Host ''
    Write-Host 'Spot-check page is open at http://127.0.0.1:8765/spotcheck'
    Write-Host 'Every click is saved immediately. Press Enter here when you are done; the local server stops.'
    [void](Read-Host)
} finally {
    if (-not $srv.HasExited) { & taskkill /PID $srv.Id /T /F | Out-Null }
    & $py scripts/spotcheck_report.py
}
