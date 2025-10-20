#!/usr/bin/env bash
set -euo pipefail

# Change to the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Pick a Python interpreter
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo "Error: Python 3 is required but was not found in PATH." >&2
  exit 1
fi

# Create a virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment (.venv)"
  "$PYTHON_BIN" -m venv .venv
fi

# Activate the virtual environment
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "Error: Could not find activation script at .venv/bin/activate" >&2
  exit 1
fi

# Upgrade pip and install dependencies
python -m pip install --upgrade pip
if [ -f "requirements.txt" ]; then
  python -m pip install -r requirements.txt
fi

# Create .env from example if missing
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Please review and edit credentials as needed."
fi

# Run the MCP server (stdio)
exec python server.py
