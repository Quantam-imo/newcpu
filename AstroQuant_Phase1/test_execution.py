import os
import sys

from execution.playwright_engine import PlaywrightEngine


def main():
	engine = PlaywrightEngine()
	login_timeout_ms = int(os.getenv("EXEC_LOGIN_TIMEOUT_MS", "120000"))
	direction = os.getenv("EXEC_TEST_DIRECTION", "BUY").strip().upper() or "BUY"

	if direction not in {"BUY", "SELL"}:
		print(f"Invalid EXEC_TEST_DIRECTION={direction!r}; expected BUY or SELL")
		return 2

	try:
		engine.start()
		# Avoid hanging forever in unattended runs.
		engine.wait_for_login(timeout_ms=login_timeout_ms)
		ok = engine.execute_market_order(direction)
		return 0 if ok else 1
	except Exception as exc:
		print(f"Execution test failed: {exc}")
		return 1
	finally:
		engine.close()


if __name__ == "__main__":
	raise SystemExit(main())
