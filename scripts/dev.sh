#!/usr/bin/env bash
# Workspace "Run" button on Replit: build once, then serve.
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/build.sh
exec bash scripts/start.sh
