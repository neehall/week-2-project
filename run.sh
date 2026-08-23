#!/usr/bin/env bash
# Convenience launcher: activates the project venv and starts the app,
# regardless of which Python is first on PATH in this terminal.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate

streamlit run app/Home.py "$@"
