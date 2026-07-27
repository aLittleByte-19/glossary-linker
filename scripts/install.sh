#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Installa glossary-linker in una virtualenv locale.

Uso:
  scripts/install.sh        installazione normale
  scripts/install.sh --dev  include dipendenze di sviluppo e test
EOF
}

DEV=0
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--dev" ]]; then
  DEV=1
elif [[ $# -gt 0 ]]; then
  usage
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [[ -z "${PYTHON:-}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "Errore: Python 3.10+ non trovato nel PATH." >&2
    exit 1
  fi
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Errore: serve Python 3.10 o superiore.")
PY

"$PYTHON" -m venv .venv

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip

if [[ "$DEV" -eq 1 ]]; then
  "$VENV_PYTHON" -m pip install -e ".[dev]"
else
  "$VENV_PYTHON" -m pip install -e .
fi

if [[ ! -f glossary-linker.local.yml && -f glossary-linker.local.example.yml ]]; then
  cp glossary-linker.local.example.yml glossary-linker.local.yml
fi

chmod +x scripts/clean_latex_artifacts.py

cat <<EOF

Installazione completata.

Avvio:
  "$PROJECT_DIR/.venv/bin/glossary-linker"

Poi apri:
  http://127.0.0.1:8765

Nota: TeX Live/MiKTeX non viene installato da questo script. Configura latexmk
o il compilatore LaTeX locale dalle Impostazioni dell'app.

Utility:
  scripts/clean_latex_artifacts.py --dry-run .
EOF
