from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from astroquant.backend.governance.prop_storage import init_db, save_state, load_state
from astroquant.backend.engines.volatility_engine import VolatilityEngine


@dataclass
class PropConfig:
    account_size: float = 50000
    static_dd_pct: float = 0.08
    daily_dd_pct: float = 0.04
    internal_daily_guard_pct: float = 0.015


class PropGovernance:

    def __init__(self, config: PropConfig):
        self.config = config
        self.phase = "PHASE1"

        self.start_balance = config.account_size
        self.static_floor = config.account_size * (1 - config.static_dd_pct)

        self.daily_high = config.account_size
        self.daily_open_equity = config.account_size
        self.daily_start = datetime.now(timezone.utc).date()

        self.trading_enabled = True
        self.profitable_days = 0
        self.day_pnl = 0
        self.phase_completion_status = "IN_PROGRESS"
        self.funded_lock_level = 52000
        self.funded_base_floor = 50000
        self.phase_target_pct = 0.08
        self.phase2_target_pct = 0.05
        self.active_account_key = "50K"
        self.active_mode = "STANDARD"
        self.phase_risk_pct = {
            "PHASE1": 0.005,
            "PHASE2": 0.004,
            "FUNDED": 0.006,
        }
        self.min_profitable_days = 3
        self.consecutive_losses = 0
        self.cooldown_active = False
        self.cooldown_end = None
        self.model_stats = {}
        self.vol_engine = VolatilityEngine()
        self.volatility_mode = "NORMAL"
        self.baseline_atr = None

        init_db()
        saved = load_state()
        if saved:
            self.phase = saved.get("phase", self.phase)
            self.profitable_days = int(saved.get("profitable_days", self.profitable_days) or 0)
            self.daily_high = float(saved.get("daily_high", self.daily_high) or self.daily_high)
            self.static_floor = float(saved.get("static_floor", self.static_floor) or self.static_floor)
            self.trading_enabled = bool(saved.get("trading_enabled", self.trading_enabled))
            self.funded_lock_level = float(saved.get("funded_lock_level", self.funded_lock_level) or self.funded_lock_level)
            self.funded_base_floor = float(saved.get("funded_base_floor", self.funded_base_floor) or self.funded_base_floor)
            self.consecutive_losses = int(saved.get("consecutive_losses", self.consecutive_losses) or 0)
            self.cooldown_active = bool(saved.get("cooldown_active", self.cooldown_active))
            cooldown_raw = saved.get("cooldown_end")
            self.cooldown_end = datetime.fromisoformat(cooldown_raw) if cooldown_raw else None
        else:
            self._persist()

    def _persist(self):
        save_state(
            self.phase,
            self.profitable_days,
            self.daily_high,
            self.static_floor,
            self.trading_enabled,
            self.funded_lock_level,
            self.funded_base_floor,
            self.consecutive_losses,
            self.cooldown_active,
            self.cooldown_end.isoformat() if self.cooldown_end else None,
        )

    def set_phase(self, phase: str):
        self.phase = phase
        self.phase_completion_status = "IN_PROGRESS"
        self.trading_enabled = True
        self._persist()

    def phase_limits(self, phase: str | None = None):
        key = str(phase or self.phase or "PHASE1").upper()
        profiles = {
            "PHASE1": {
                "risk_pct": float(self.phase_risk_pct.get("PHASE1", 0.005)),
                "max_trades_per_day": 3,
                "confidence_threshold": 75.0,
                "daily_halt_pct": 0.02,
                "news_freeze_pre_minutes": 20,
                "news_freeze_post_minutes": 20,
                "reduce_risk_profit_pct": 0.04,
                "reduced_risk_pct": 0.003,
            },
            "PHASE2": {
                "risk_pct": float(self.phase_risk_pct.get("PHASE2", 0.004)),
                "max_trades_per_day": 2,
                "confidence_threshold": 77.0,
                "daily_halt_pct": 0.02,
                "news_freeze_pre_minutes": 20,
                "news_freeze_post_minutes": 20,
                "reduce_risk_profit_pct": 0.03,
                "reduced_risk_pct": 0.003,
            },
            "FUNDED": {
                "risk_pct": float(self.phase_risk_pct.get("FUNDED", 0.006)),
                "max_trades_per_day": 2,
                "confidence_threshold": 72.0,
                "daily_halt_pct": 0.025,
                "news_freeze_pre_minutes": 20,
                "news_freeze_post_minutes": 20,
                "reduce_risk_profit_pct": 0.03,
                "reduced_risk_pct": 0.004,
            },
        }
        return profiles.get(key, profiles["PHASE1"])

    def apply_profile(self, profile: dict):
        payload = dict(profile or {})
        account_size = max(1000.0, float(payload.get("account_size", self.config.account_size)))
        self.config.account_size = account_size
        self.start_balance = account_size

        self.active_account_key = str(payload.get("account_key") or self.active_account_key)
        self.active_mode = str(payload.get("mode") or self.active_mode).upper()

        max_dd_pct = float(payload.get("max_dd_pct", 8.0)) / 100.0
        daily_dd_pct = float(payload.get("daily_dd_pct", 4.0)) / 100.0

        self.config.static_dd_pct = max(0.01, min(0.5, max_dd_pct))
        self.config.daily_dd_pct = max(0.005, min(0.3, daily_dd_pct))
        self.config.internal_daily_guard_pct = self.config.daily_dd_pct

        self.static_floor = account_size * (1 - self.config.static_dd_pct)
        self.daily_open_equity = account_size
        self.daily_high = max(self.daily_high, account_size)

        self.phase_target_pct = float(payload.get("phase1_target_pct", 8.0)) / 100.0
        self.phase2_target_pct = float(payload.get("phase2_target_pct", 5.0)) / 100.0

        self.phase_risk_pct = {
            "PHASE1": float(payload.get("phase1_risk", 0.6)) / 100.0,
            "PHASE2": float(payload.get("phase2_risk", 0.5)) / 100.0,
            "FUNDED": float(payload.get("funded_risk", 0.4)) / 100.0,
        }

        self.funded_base_floor = account_size
        self.funded_lock_level = round(account_size * 1.04, 2)
        self._persist()

    def apply_account_size(self, account_size: float):
        size = max(1000.0, float(account_size))
        self.config.account_size = size
        self.start_balance = size
        self.config.static_dd_pct = 0.08
        self.config.daily_dd_pct = 0.04
        self.config.internal_daily_guard_pct = self.phase_limits().get("daily_halt_pct", 0.02)
        self.static_floor = size * (1 - self.config.static_dd_pct)
        self.daily_open_equity = size
        self.daily_high = max(self.daily_high, size)
        self.phase_target_pct = 0.08
        self.phase2_target_pct = 0.05
        self.funded_base_floor = size
        self.funded_lock_level = round(size * 1.04, 2)
        self._persist()

    def phase_target_reached(self, equity):
        if self.phase == "PHASE1":
            return equity >= self.config.account_size * (1.0 + float(self.phase_target_pct))

        if self.phase == "PHASE2":
            return equity >= self.config.account_size * (1.0 + float(self.phase2_target_pct))

        return False

    def update_volatility(self, highs, lows, closes, baseline_atr=None):
        atr = self.vol_engine.calculate_atr(highs, lows, closes)

        reference = baseline_atr
        if reference is None:
            reference = self.baseline_atr

        state = self.vol_engine.volatility_state(atr, reference)
        self.volatility_mode = state

        if atr is not None:
            if self.baseline_atr is None:
                self.baseline_atr = atr
            else:
                self.baseline_atr = (self.baseline_atr * 0.9) + (atr * 0.1)

        return state

    def get_session(self):
        hour = datetime.now(timezone.utc).hour

        if 0 <= hour < 7:
            return "ASIA"
        elif 7 <= hour < 13:
            return "LONDON"
        return "NEWYORK"

    def get_phase_risk(self, news_spike=False):
        limits = self.phase_limits(self.phase)
        base_risk = float(limits.get("risk_pct", 0.005))

        if self.day_pnl >= (float(self.config.account_size) * float(limits.get("reduce_risk_profit_pct", 0.04))):
            base_risk = min(base_risk, float(limits.get("reduced_risk_pct", base_risk)))

        session = self.get_session()
        if session == "ASIA":
            base_risk *= 0.8

        if self.volatility_mode == "HIGH":
            base_risk *= 0.7
        elif self.volatility_mode == "EXTREME":
            base_risk *= 0.5

        if news_spike:
            base_risk = min(base_risk, 0.002)

        return base_risk

    def funded_protection(self, equity):
        if self.phase != "FUNDED":
            return "NOT_FUNDED"

        if equity < self.funded_base_floor:
            self.trading_enabled = False
            self._persist()
            return "FUNDED_FLOOR_BREACH"

        return "OK"

    def register_trade_result(self, pnl, model_name=None):
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if model_name:
            if model_name not in self.model_stats:
                self.model_stats[model_name] = {"wins": 0, "losses": 0}
            if pnl > 0:
                self.model_stats[model_name]["wins"] += 1
            else:
                self.model_stats[model_name]["losses"] += 1

        if self.consecutive_losses == 2:
            self.cooldown_active = True
            self.cooldown_end = datetime.now(timezone.utc) + timedelta(hours=4)

        if self.consecutive_losses >= 3:
            self.trading_enabled = False

        self._persist()

    def check_cooldown(self):
        if not self.cooldown_active:
            return "OK"

        now = datetime.now(timezone.utc)
        if self.cooldown_end and now < self.cooldown_end:
            return "COOLDOWN_ACTIVE"

        self.cooldown_active = False
        self.cooldown_end = None
        self._persist()
        return "OK"

    def update_equity(self, equity: float):
        today = datetime.now(timezone.utc).date()

        if today != self.daily_start:
            if self.day_pnl > 0:
                self.profitable_days += 1
            self.daily_start = today
            self.daily_high = equity
            self.daily_open_equity = equity
            self.day_pnl = 0

        if equity > self.daily_high:
            self.daily_high = equity

        self.day_pnl = equity - self.daily_open_equity

        limits = self.phase_limits(self.phase)
        daily_halt_amount = float(self.config.account_size) * float(limits.get("daily_halt_pct", 0.02))
        if self.day_pnl <= -daily_halt_amount:
            self.trading_enabled = False
            self._persist()
            return "DAILY_HARD_STOP"

        if self.phase == "FUNDED":
            funded_status = self.funded_protection(equity)
            if funded_status != "OK":
                self._persist()
                return funded_status

        if equity <= self.static_floor:
            self.trading_enabled = False
            self._persist()
            return "STATIC_DD_BREACH"

        if (self.daily_high - equity) >= self.config.account_size * self.config.internal_daily_guard_pct:
            self.trading_enabled = False
            self._persist()
            return "DAILY_GUARD_TRIGGERED"

        if self.phase_target_reached(equity):
            if self.profitable_days < int(self.min_profitable_days):
                self._persist()
                return "TARGET_REACHED_BUT_MIN_DAYS_NOT_MET"

            if self.phase == "PHASE1":
                self.phase = "PHASE2"
                self.phase_completion_status = "PHASE1_COMPLETED"
                self.trading_enabled = True
                self.daily_open_equity = equity
                self.daily_high = max(self.daily_high, equity)
                self._persist()
                return "PHASE_UPGRADED_PHASE2"

            if self.phase == "PHASE2":
                self.phase = "FUNDED"
                self.phase_completion_status = "PHASE2_COMPLETED"
                self.trading_enabled = True
                self.funded_base_floor = max(self.funded_base_floor, float(self.config.account_size))
                self.funded_lock_level = max(self.funded_lock_level, round(float(self.config.account_size) * 1.04, 2))
                self.daily_open_equity = equity
                self.daily_high = max(self.daily_high, equity)
                self._persist()
                return "PHASE_UPGRADED_FUNDED"

            self.trading_enabled = False
            self.phase_completion_status = "PHASE_COMPLETED"
            self._persist()
            return "PHASE_COMPLETED"

        self._persist()

        return "OK"

    def can_trade(self):
        return self.trading_enabled

    def compute_auto_behavior_profile(
        self,
        equity: float,
        daily_loss: float,
        drawdown: float,
        news_mode: str = "NORMAL",
        phase: str | None = None,
        volatility_mode: str | None = None,
        trading_enabled: bool | None = None,
        cooldown_active: bool | None = None,
    ):
        phase = str(phase or self.phase or "PHASE1").upper()
        volatility = str(volatility_mode or self.volatility_mode or "NORMAL").upper()
        news_state = str(news_mode or "NORMAL").upper()
        trading_enabled_flag = self.trading_enabled if trading_enabled is None else bool(trading_enabled)
        cooldown_active_flag = self.cooldown_active if cooldown_active is None else bool(cooldown_active)

        daily_guard_limit = self.config.account_size * self.config.internal_daily_guard_pct
        daily_guard_used = (float(daily_loss) / daily_guard_limit) if daily_guard_limit > 0 else 0.0

        target_equity = (
            self.config.account_size * (1.0 + float(self.phase_target_pct))
            if phase == "PHASE1"
            else (self.config.account_size * (1.0 + float(self.phase2_target_pct)) if phase == "PHASE2" else self.funded_lock_level)
        )
        target_left = max(0.0, float(target_equity) - float(equity))

        mode = "BALANCED"
        risk_multiplier = 1.0
        hard_block = False
        reasons = []

        if not trading_enabled_flag:
            mode = "HALT"
            risk_multiplier = 0.0
            hard_block = True
            reasons.append("Trading disabled by governance")

        if cooldown_active_flag:
            mode = "COOLDOWN"
            risk_multiplier = 0.0
            hard_block = True
            reasons.append("Cooldown active")

        if news_state == "HALT":
            mode = "NEWS_LOCK"
            risk_multiplier = 0.0
            hard_block = True
            reasons.append("High-impact news halt")

        if daily_guard_used >= 0.85 and not hard_block:
            mode = "CAPITAL_PRESERVE"
            risk_multiplier = 0.35
            reasons.append("Daily buffer nearly exhausted")

        if volatility == "EXTREME" and not hard_block:
            mode = "DEFENSIVE"
            risk_multiplier = min(risk_multiplier, 0.5)
            reasons.append("Extreme volatility")
        elif volatility == "HIGH" and not hard_block:
            mode = "BALANCED"
            risk_multiplier = min(risk_multiplier, 0.75)
            reasons.append("High volatility")

        if phase == "FUNDED" and not hard_block:
            mode = "FUNDED_DEFENSIVE"
            risk_multiplier = min(risk_multiplier, 0.7)
            reasons.append("Funded capital protection mode")

        if phase == "PHASE2" and target_left <= self.config.account_size * 0.01 and not hard_block:
            mode = "LOCK_IN"
            risk_multiplier = min(risk_multiplier, 0.5)
            reasons.append("Near phase target, locking in")

        phase_limits = self.phase_limits(phase)
        phase_daily_halt = float(self.config.account_size) * float(phase_limits.get("daily_halt_pct", 0.02))
        if float(daily_loss) >= phase_daily_halt and not hard_block:
            mode = "HALT"
            risk_multiplier = 0.0
            hard_block = True
            reasons.append("Daily hard-stop reached")

        static_floor_buffer = max(0.0, float(equity) - float(self.static_floor))

        return {
            "mode": mode,
            "risk_multiplier": round(float(risk_multiplier), 4),
            "hard_block": bool(hard_block),
            "reasons": reasons,
            "phase": phase,
            "volatility_mode": volatility,
            "news_mode": news_state,
            "daily_guard_used_pct": round(daily_guard_used * 100.0, 2),
            "daily_guard_limit": round(daily_guard_limit, 2),
            "target_left": round(target_left, 2),
            "drawdown": round(float(drawdown), 2),
            "static_floor_buffer": round(static_floor_buffer, 2),
            "cooldown_active": bool(cooldown_active_flag),
        }

    def auto_behavior_profile(
        self,
        equity: float,
        daily_loss: float,
        drawdown: float,
        news_mode: str = "NORMAL",
    ):
        return self.compute_auto_behavior_profile(
            equity=equity,
            daily_loss=daily_loss,
            drawdown=drawdown,
            news_mode=news_mode,
            phase=self.phase,
            volatility_mode=self.volatility_mode,
            trading_enabled=self.trading_enabled,
            cooldown_active=self.cooldown_active,
        )
