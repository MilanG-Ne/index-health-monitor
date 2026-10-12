#!/usr/bin/env bash
# Installs dependencies and builds the React app into web/dist.
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -r requirements.txt
cd web
npm ci
npm run build
