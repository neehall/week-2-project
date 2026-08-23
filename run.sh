#!/usr/bin/env bash
# Convenience launcher: activates the project venv and starts the app,
# regardless of which Python is first on PATH in this terminal.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate

# `streamlit run app/Home.py` only puts app/'s own directory on sys.path,
# not the project root — Home.py's `from app.common import config` (and
# every app.core.* import) needs the root itself on the path.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

streamlit run app/Home.py "$@"
