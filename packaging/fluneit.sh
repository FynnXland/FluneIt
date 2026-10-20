#!/usr/bin/env bash
# Linux (experimental): starts FluneIt from .venv-linux (see setup_linux.sh).
cd "$(dirname "$0")/.."
exec .venv-linux/bin/python -m fluneit "$@"
