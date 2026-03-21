import datetime
import json
from astroquant.engine.model_weight_engine import ModelWeightEngine
from astroquant.engine.performance_memory_engine import PerformanceMemory
from astroquant.engine.frequency_engine import FrequencyEngine
from astroquant.backend.journal.ai_trade_journal import init_journal, save_trade, generate_narrative


class JournalEngine:

	def __init__(self, state):
		self.state = state
		self.weight_engine = ModelWeightEngine()
		self.memory = PerformanceMemory()
		self.freq_engine = FrequencyEngine()
		init_journal()

	def log_trade(self, trade):

		trade["timestamp"] = str(datetime.datetime.now())

		with open("logs/trade_log.json", "a") as f:
			f.write(json.dumps(trade) + "\n")

	def close_trade(self, model, pnl, trade_context=None):

		self.state.balance += pnl

		if pnl < 0:
			self.state.consecutive_losses += 1
			self.state.daily_loss += abs(pnl)
		else:
			self.state.consecutive_losses = 0

		if model not in self.state.model_performance:
			self.state.model_performance[model] = {"wins": 0, "losses": 0}

		if pnl > 0:
			self.state.model_performance[model]["wins"] += 1
			self.weight_engine.record_trade(model, "win")
			result = "win"
		else:
			self.state.model_performance[model]["losses"] += 1
			self.weight_engine.record_trade(model, "loss")
			result = "loss"

		if trade_context:
			self.memory.record_trade(
				model=model,
				symbol=trade_context.get("symbol", "UNKNOWN"),
				session=trade_context.get("session", "ASIA"),
				volatility=trade_context.get("volatility", "NORMAL"),
				news_mode=trade_context.get("news_mode", "NORMAL"),
				result=result,
			)

			self.freq_engine.record_trade(
				symbol=trade_context.get("symbol", "UNKNOWN"),
				result=result,
				session=trade_context.get("session", "UNKNOWN"),
			)

			risk_percent = float(trade_context.get("risk", 0.0) or 0.0)
			account_size = float(trade_context.get("account_size", 50000.0) or 50000.0)
			risk_amount = max(1e-9, risk_percent * account_size)
			r_multiple = float(pnl) / risk_amount

			news_status = trade_context.get("news_mode", "NORMAL")
			narrative = generate_narrative(
				model=model,
				volatility=trade_context.get("volatility_mode", trade_context.get("volatility", "NORMAL")),
				session=trade_context.get("session", "ASIA"),
				news_status=news_status,
				rr=trade_context.get("rr", 0.0),
			)

			save_trade({
				"phase": trade_context.get("phase", "PHASE1"),
				"symbol": trade_context.get("symbol", "UNKNOWN"),
				"model": model,
				"entry_reason": trade_context.get("entry_reason", "AI-ranked signal selection"),
				"risk": risk_percent,
				"volatility": trade_context.get("volatility_mode", trade_context.get("volatility", "NORMAL")),
				"session": trade_context.get("session", "ASIA"),
				"news_status": news_status,
				"rr": float(trade_context.get("rr", 0.0) or 0.0),
				"entry_price": float(trade_context.get("entry_price", 0.0) or 0.0),
				"sl": float(trade_context.get("sl", 0.0) or 0.0),
				"tp": float(trade_context.get("tp", 0.0) or 0.0),
				"exit_price": float(trade_context.get("exit_price", 0.0) or 0.0),
				"result": "WIN" if pnl > 0 else "LOSS",
				"r_multiple": r_multiple,
				"pnl": float(pnl),
				"confidence": float(trade_context.get("confidence", 0.0) or 0.0),
				"governance_snapshot": json.dumps(trade_context.get("governance_snapshot", {})),
				"narrative": narrative,
			})
