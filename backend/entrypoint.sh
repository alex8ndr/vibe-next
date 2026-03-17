#!/bin/sh
set -e

# Ensure data is available (downloads from B2 if missing/stale)
python scripts/ensure_data.py

# Start the application
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
