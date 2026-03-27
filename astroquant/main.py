# This file is kept for backwards compatibility only.
# The production entry point is: astroquant/backend/main.py
# Run with: uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000
#
# Do NOT launch this file directly — it will not start the trading system.
raise SystemExit(
    "astroquant/main.py is deprecated. "
    "Start the server with: uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000"
)