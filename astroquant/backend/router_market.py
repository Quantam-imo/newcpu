import os
from fastapi import APIRouter, Response, Request
from typing import Any


router = APIRouter()

# Explicit OPTIONS handler for CORS preflight (must be after router = APIRouter())
@router.options("/chart/data")
def options_chart_data(response: Response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return Response(status_code=204)


# Real endpoint for chart data

import logging
from astroquant.engine.candle.candle_reader import get_candle_series, get_latest_candle


@router.get("/chart/data")
def get_chart_data(symbol: str = "GC.FUT", timeframe: str = "1", limit: int = 80) -> Any:
	error_msgs = []
	try:
		candles = get_candle_series(symbol, timeframe, limit)
	except Exception as e:
		candles = []
		error_msgs.append(f"Redis error: {e}")

	dataset = os.environ.get("DATABENTO_DATASET", "GLBX.MDP3")
	schema = "ohlcv-1m"

	# Databento fallback with timeout and logging
	if not candles:
		try:
			import databento as db
			from datetime import datetime, timezone, timedelta
			import concurrent.futures
			api_key = os.environ.get("DATABENTO_API_KEY")
			if api_key:
				now = datetime.now(timezone.utc)
				end_time = now.replace(second=0, microsecond=0)
				start_time = end_time - timedelta(minutes=int(limit))
				client = db.Historical(api_key)

				def fetch_db(start, end):
					return client.timeseries.get_range(
						dataset=dataset,
						schema=schema,
						symbols=[symbol],
						start=start.isoformat(),
						end=end.isoformat()
					)

				with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
					future = executor.submit(fetch_db, start_time, end_time)
					try:
						result = future.result(timeout=15)
						df = result.to_df()
						if not df.empty:
							candles = df.reset_index().to_dict(orient="records")
						else:
							error_msgs.append("Databento returned empty DataFrame.")
					except Exception as e:
						# If error is 422 and contains 'data_end_after_available_end', retry with available_end
						msg = str(e)
						logging.error(f"Databento error: {msg}")
						if "data_end_after_available_end" in msg:
							import re
							# Extract available_end from error message
							match = re.search(r"data available up to '([^']+)'", msg)
							if match:
								available_end_str = match.group(1)
								available_end = datetime.fromisoformat(available_end_str)
								new_start = available_end - timedelta(minutes=int(limit))
								future2 = executor.submit(fetch_db, new_start, available_end)
								try:
									result2 = future2.result(timeout=15)
									df2 = result2.to_df()
									if not df2.empty:
										candles = df2.reset_index().to_dict(orient="records")
									else:
										error_msgs.append("Databento (retry) returned empty DataFrame.")
								except Exception as e2:
									error_msgs.append(f"Databento retry error: {e2}")
									logging.error(f"Databento retry error: {e2}")
							else:
								error_msgs.append("Could not parse available_end from Databento error.")
						else:
							error_msgs.append(f"Databento error: {msg}")
			else:
				error_msgs.append("Missing DATABENTO_API_KEY.")
				logging.error("Missing DATABENTO_API_KEY.")
		except Exception as e:
			candles = []
			error_msgs.append(f"Databento error (outer): {e}")
			logging.error(f"Databento error (outer): {e}")

	if not candles:
		error_msgs.append("No real candles available from Redis or Databento.")
		return {
			"candles": [],
			"meta": {
				"count": 0,
				"errors": error_msgs if error_msgs else None
			},
			"overlays": {},
			"signals": []
		}

# Minimal /equity endpoint for dashboard integration
@router.get("/equity")
def get_equity(request: Request):
	from astroquant.backend.database import get_connection
	conn = get_connection()
	cur = conn.cursor()
	cur.execute("SELECT SUM(balance) FROM accounts WHERE active=1")
	equity = cur.fetchone()[0] or 0.0
	cur.execute("SELECT base_balance, target_balance, primary_account FROM portfolio_meta LIMIT 1")
	row = cur.fetchone()
	base = row[0] if row else 0.0
	target = row[1] if row else 0.0
	primary_account = row[2] if row else "50K"
	return {
		"equity": equity,
		"base": base,
		"target": target,
		"primary_account": primary_account
	}

# Minimal /market/orderflow_summary endpoint for chart/dashboard integration
@router.get("/market/orderflow_summary")
def get_orderflow_summary(symbol: str = "GC.FUT", timeframe: str = "1m"):
	from astroquant.engine.candle.candle_reader import get_candle_series
	candles = get_candle_series(symbol, timeframe, limit=120)
	buy_aggression = sum(c["volume"] for c in candles if c["close"] > c["open"])
	sell_aggression = sum(c["volume"] for c in candles if c["close"] < c["open"])
	delta = buy_aggression - sell_aggression
	cumulative_delta = sum(c["close"] - c["open"] for c in candles)
	dom_spread = max(c["high"] - c["low"] for c in candles) if candles else 0.0
	iceberg_count = sum(1 for c in candles if c["volume"] > 1000)
	confidence = min(100.0, (buy_aggression + sell_aggression) / max(1, len(candles)))
	regime_mode = "BULLISH" if delta > 0 else "BEARISH"
	alert_level = "LOW" if abs(delta) < 1000 else "HIGH"
	absorption = "NEUTRAL"
	imbalance = "NONE"
	narrative = f"Orderflow: {regime_mode}, delta={delta}, volume={buy_aggression+sell_aggression}"
	signal_strength = confidence
	return {
		"summary": {
			"regime_mode": regime_mode,
			"alert_level": alert_level,
			"signal_strength": signal_strength,
			"buy_aggression": buy_aggression,
			"sell_aggression": sell_aggression,
			"delta": delta,
			"cumulative_delta": cumulative_delta,
			"imbalance": imbalance,
			"dom_spread": dom_spread,
			"iceberg_count": iceberg_count,
			"absorption": absorption,
			"confidence": confidence,
			"narrative": narrative
		}
	}

# Placeholder endpoint for dashboard multi-symbol
@router.get("/dashboard/multi_symbol")
def get_multi_symbol_dashboard() -> Any:
	return {
		"rows": [
			{"symbol": "GC.FUT", "market": {"htf_bias": "BULL", "ltf_structure": "UP"}, "model": {"active_model": "AI", "confidence": 95}, "risk": {"risk_percent": 1.2, "phase": "PHASE1"}, "prop_behavior": {"mode": "STANDARD"}, "basis": {"status": "OK"}, "resolver": {"status": "OK", "watch_only": False}, "market": {"news_state": "Normal"}, "broker_price": 2110, "system_price": 2109, "offset_diff": 1.0},
		],
		"feed": {"healthy": True},
		"timestamp": 1710556900
	}
