#!/usr/bin/env bash
#
# setup.sh — one-command install for File → Markdown.
#
# Creates a Python virtual environment, installs backend dependencies, and
# installs frontend npm packages. Run from the project root:
#
#     ./setup.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
info() { printf "\033[36m›\033[0m %s\n" "$1"; }
warn() { printf "\033[33m!\033[0m %s\n" "$1"; }

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
bold "Checking prerequisites…"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10+ is required but was not found." >&2
  exit 1
fi
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
info "Found Python $PY_VER"

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js 18+ is required but was not found." >&2
  exit 1
fi
info "Found Node $(node --version)"

if command -v ffmpeg >/dev/null 2>&1; then
  info "Found ffmpeg (audio/video transcription enabled)"
else
  warn "ffmpeg not found — audio/video transcription will be disabled."
  warn "  macOS:  brew install ffmpeg"
  warn "  Ubuntu: sudo apt install ffmpeg"
fi

if command -v tesseract >/dev/null 2>&1; then
  info "Found tesseract (image OCR enabled)"
else
  warn "tesseract not found — image OCR will be skipped."
  warn "  macOS:  brew install tesseract"
  warn "  Ubuntu: sudo apt install tesseract-ocr"
fi

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------
bold "Setting up backend…"
cd "$BACKEND"
if [ ! -d ".venv" ]; then
  info "Creating virtual environment (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
info "Upgrading pip"
python -m pip install --upgrade pip >/dev/null
info "Installing Python dependencies (this can take several minutes)…"
pip install -r requirements.txt
deactivate

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
bold "Setting up frontend…"
cd "$FRONTEND"
info "Installing npm dependencies…"
npm install

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
bold "✅ Setup complete!"
cat <<'EOF'

Run the app in two terminals:

  Terminal 1 — backend:
    cd backend && source .venv/bin/activate && uvicorn main:app --reload --port 8000

  Terminal 2 — frontend:
    cd frontend && npm run dev

Then open http://localhost:5173

Or with Docker:
    docker compose up --build
EOF
