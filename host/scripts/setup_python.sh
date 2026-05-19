#!/usr/bin/env bash
# Install pyenv (if missing), the Python version pinned in host/.python-version,
# then create host/.venv and pip install requirements.
# Must run as a regular (non-root) user so pyenv lands under $HOME.
#
# Run from anywhere:
#   bash host/scripts/setup_python.sh

set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Please run as a regular user (not root): bash host/scripts/setup_python.sh" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_VERSION="$(tr -d '[:space:]' <"$PROJECT_DIR/.python-version" 2>/dev/null || echo 3.13.5)"
VENV="$PROJECT_DIR/.venv"

export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"

if [[ ! -d "$PYENV_ROOT" ]]; then
  echo "==> Installing pyenv into $PYENV_ROOT"
  curl -fsSL https://pyenv.run | bash
else
  echo "==> pyenv already present at $PYENV_ROOT"
fi

export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

if ! pyenv versions --bare | grep -qx "$PYTHON_VERSION"; then
  echo "==> Building Python $PYTHON_VERSION via pyenv (this can take ~15 min on RPi5)"
  pyenv install "$PYTHON_VERSION"
else
  echo "==> Python $PYTHON_VERSION already built via pyenv"
fi

PYBIN="$PYENV_ROOT/versions/$PYTHON_VERSION/bin/python"

if [[ ! -d "$VENV" ]]; then
  echo "==> Creating venv at $VENV"
  "$PYBIN" -m venv "$VENV"
else
  echo "==> Venv already exists at $VENV"
fi

echo "==> Upgrading pip"
"$VENV/bin/pip" install --upgrade pip

echo "==> Installing dependencies"
"$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

cat <<EOF

Done.
  Python : $("$VENV/bin/python" --version)
  Venv   : $VENV

If pyenv is not yet on your shell PATH, append to ~/.bashrc:
  export PYENV_ROOT="\$HOME/.pyenv"
  export PATH="\$PYENV_ROOT/bin:\$PATH"
  eval "\$(pyenv init -)"
EOF
