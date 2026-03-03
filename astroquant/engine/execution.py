from execution.playwright_engine import PlaywrightExecutionEngine


class ExecutionEngine:

	def __init__(self):
		self.playwright = PlaywrightExecutionEngine()

	def set_page(self, page):
		self.playwright.set_page(page)

	def set_reconnect_handler(self, handler):
		self.playwright.set_reconnect_handler(handler)

	def execute(self, signal, lot_size, page=None):
		return self.playwright.execute(signal, lot_size, page=page)

	def execution_health(self):
		return self.playwright.execution_health()

	def is_halted(self):
		return bool(self.playwright.execution_health().get("execution_status") == "HALTED")

	def emergency_halt(self, reason):
		self.playwright.emergency_halt(reason)

	def broker_positions_snapshot(self):
		return self.playwright.broker_positions_snapshot()

	def broker_equity_snapshot(self):
		return self.playwright.broker_equity_snapshot()

	def broker_quote_snapshot(self, expected_symbols=None):
		return self.playwright.broker_quote_snapshot(expected_symbols=expected_symbols)
