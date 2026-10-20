#!/usr/bin/env bash
# Startet Fluneit aus dem virtuellen Environment (siehe setup_linux.sh).
cd "$(dirname "$0")"
exec .venv-linux/bin/python fluneit.py "$@"
