#!/usr/bin/env bash
# Starts the app. --proxy-headers makes login redirects use https behind Replit's proxy.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uvicorn server.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
