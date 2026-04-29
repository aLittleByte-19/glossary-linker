param(
    [switch]$Dev,
    [switch]$Help
)

if ($Help) {
    Write-Host @"
Installa glossary-linker in una virtualenv locale.

Uso:
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Dev
"@
    exit 0
}

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $ProjectDir

$Python = Get-Command py -ErrorAction SilentlyContinue
if ($Python) {
    $PythonArgs = @("-3")
    $PythonExe = "py"
}
else {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Python) {
        Write-Error "Python 3.10+ non trovato nel PATH."
        exit 1
    }
    $PythonArgs = @()
    $PythonExe = "python"
}

& $PythonExe @PythonArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 'Errore: serve Python 3.10 o superiore.')"
& $PythonExe @PythonArgs -m venv .venv

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip

if ($Dev) {
    & $VenvPython -m pip install -e ".[dev]"
}
else {
    & $VenvPython -m pip install -e .
}

if ((-not (Test-Path "glossary-linker.local.yml")) -and (Test-Path "glossary-linker.local.example.yml")) {
    Copy-Item "glossary-linker.local.example.yml" "glossary-linker.local.yml"
}

$Launcher = Join-Path $ProjectDir ".venv\Scripts\glossary-linker.exe"
Write-Host ""
Write-Host "Installazione completata."
Write-Host ""
Write-Host "Avvio:"
Write-Host "  $Launcher"
Write-Host ""
Write-Host "Poi apri:"
Write-Host "  http://127.0.0.1:8765"
Write-Host ""
Write-Host "Nota: TeX Live/MiKTeX non viene installato da questo script. Configura latexmk"
Write-Host "o il compilatore LaTeX locale dalle Impostazioni dell'app."
Write-Host ""
Write-Host "Utility:"
Write-Host "  .\.venv\Scripts\python.exe scripts\reset_test_documents.py --dry-run"
Write-Host "  .\.venv\Scripts\python.exe scripts\clean_latex_artifacts.py --dry-run ."
