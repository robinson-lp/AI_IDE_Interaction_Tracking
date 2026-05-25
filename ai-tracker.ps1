# ai-tracker.ps1 — run the AI Tracker CLI without a system Python install
$py = "C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe"
$projectDir = $PSScriptRoot
& $py -c "import sys; sys.path.insert(0, r'$projectDir'); from ai_tracker.cli import main; main()" @args
