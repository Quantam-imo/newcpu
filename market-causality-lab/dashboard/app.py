"""
Market Causality Lab - Dashboard Server

Serves the professional HTML dashboard that displays comprehensive
market causality intelligence analysis with AI model integration,
drift monitoring, and trade-level recommendations.

Usage:
    python app.py                    # Development mode (localhost:5000)
    gunicorn app:app -b 0.0.0.0:5000 # Production mode

The dashboard connects to the main market-causality-lab API endpoints:
  - /market_causality/summary  (backend router_market_causality.py)
  
No database needed—dashboard is purely frontend, pulling live analysis
from the backend router which calls the core intelligence pipeline.
"""

from flask import Flask, request, Response
from pathlib import Path
import os
import urllib.request
import urllib.error

app = Flask(__name__, static_folder=None)

BACKEND_BASE = os.environ.get("BACKEND_BASE", "http://127.0.0.1:8000")


def _proxy(path):
    """Forward a request to the FastAPI backend and stream the response back."""
    qs = request.query_string.decode()
    url = f"{BACKEND_BASE}/{path}"
    if qs:
        url += "?" + qs
    try:
        req = urllib.request.Request(
            url,
            data=request.get_data() or None,
            method=request.method,
            headers={k: v for k, v in request.headers if k.lower() not in ("host", "content-length")},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            ct = resp.headers.get("Content-Type", "application/json")
            return Response(body, status=resp.status, content_type=ct)
    except urllib.error.HTTPError as e:
        return Response(e.read(), status=e.code, content_type="application/json")
    except Exception as e:
        return Response(f'{{"error":"{e}"}}', status=502, content_type="application/json")


@app.route("/market_causality/<path:subpath>", methods=["GET", "POST"])
def proxy_market_causality(subpath):
    return _proxy(f"market_causality/{subpath}")


@app.route("/api/astro/<path:subpath>", methods=["GET", "POST"])
def proxy_api_astro(subpath):
    return _proxy(f"api/astro/{subpath}")


@app.route("/")
def dashboard():
    """Serve the MCL intelligence dashboard HTML."""
    dashboard_path = Path(__file__).parent / "index.html"
    
    if dashboard_path.exists():
        with open(dashboard_path, "r") as f:
            html_content = f.read()
        # Render with Flask to support any template variables if needed
        return html_content
    else:
        return "<h1>MCL Dashboard</h1><p>Dashboard HTML not found.</p>", 404


@app.route("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "market-causality-lab-dashboard",
        "dashboard": "available"
    }


if __name__ == "__main__":
    # Development mode
    port = int(os.environ.get("MCL_DASHBOARD_PORT", 5000))
    print(f"🚀 Market Causality Lab Dashboard running on http://localhost:{port}")
    print("   Access dashboard at: http://localhost:{port}")
    print("   Note: Requires backend router at http://localhost:8000/market_causality/summary")
    app.run(debug=True, host="0.0.0.0", port=port)