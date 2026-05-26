# ai-tracker.ps1 — run the AI Tracker CLI using the project's venv Python
$projectDir = $PSScriptRoot
$venvPy = Join-Path $projectDir ".venv\Scripts\python.exe"
$sysPyCmd = Get-Command python -ErrorAction SilentlyContinue
$sysPy = if ($sysPyCmd) { $sysPyCmd.Source } else { $null }

$py = if (Test-Path $venvPy) { $venvPy } elseif ($sysPy) { $sysPy } else {
    Write-Error "Python not found. Run: python -m venv .venv && .venv\Scripts\pip install -e ."
    exit 1
}

& $py -m ai_tracker.cli @args
