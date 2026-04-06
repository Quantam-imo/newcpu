"""
AstroQuant Market Calendar Engine
==================================
Provides real-time market open/closed status, holiday detection, early-close
awareness, and next-open countdown for all traded instruments.

Usage:
    from astroquant.engine.market_calendar import MarketCalendar

    info = MarketCalendar.get_session_info("XAUUSD")
    # {"is_open": False, "reason": "Weekend", "next_open": "2026-04-06 18:00 UTC", ...}

    if not MarketCalendar.is_market_open("XAUUSD"):
        print(MarketCalendar.format_closure_message("XAUUSD"))
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import pandas_market_calendars, fall back gracefully if missing
# ---------------------------------------------------------------------------
try:
    import pandas_market_calendars as mcal
    import pandas as pd
    _HAS_MCAL = True
except ImportError:
    _HAS_MCAL = False
    _log.warning("pandas_market_calendars not installed — MarketCalendar running in ALWAYS-OPEN fallback mode")


# ---------------------------------------------------------------------------
# Symbol → calendar mapping
# ---------------------------------------------------------------------------
_SYMBOL_CALENDARS: dict[str, str] = {
    # Gold / Precious Metals
    "XAUUSD":  "CMEGlobex_Gold",
    "GC.FUT":  "CMEGlobex_Gold",
    "GC":      "CMEGlobex_Gold",
    "SI.FUT":  "CMEGlobex_Gold",

    # Equity index futures
    "NQ":      "CME_Equity",
    "NQ.FUT":  "CME_Equity",
    "ES":      "CME_Equity",
    "ES.FUT":  "CME_Equity",
    "US30":    "CME_Equity",
    "YM.FUT":  "CME_Equity",
    "RTY.FUT": "CME_Equity",

    # FX futures (CME)
    "EURUSD":  "CMEGlobex_FX",
    "6E.FUT":  "CMEGlobex_FX",
    "GBPUSD":  "CMEGlobex_FX",
    "6B.FUT":  "CMEGlobex_FX",
    "USDJPY":  "CMEGlobex_FX",
    "6J.FUT":  "CMEGlobex_FX",

    # Energy (CME Globex)
    "CL.FUT":  "CMEGlobex_Energy",
    "NG.FUT":  "CMEGlobex_Energy",

    # Default / unknown
    "DEFAULT": "CME_TradeDate",
}

# Holiday names sourced from pandas_market_calendars regular_holidays
# Used for friendly display (e.g. "Memorial Day", "Good Friday")
_HOLIDAY_DISPLAY_NAMES: dict[str, str] = {
    "New Years Day":                  "New Year's Day",
    "Good Friday 1908+":              "Good Friday",
    "Christmas":                      "Christmas Day",
    "Dr. Martin Luther King Jr. Day": "MLK Jr. Day",
    "Presidents Day":                 "Presidents' Day",
    "Memorial Day":                   "Memorial Day",
    "Juneteenth Starting at 2022":    "Juneteenth",
    "July 4th":                       "Independence Day (Early Close)",
    "Labor Day":                      "Labor Day (Early Close)",
    "Thanksgiving":                   "Thanksgiving (Early Close)",
    "Friday after Thanksgiving":      "Black Friday (Early Close)",
}

# Cache calendars to avoid repeated expensive lookups
_calendar_cache: dict[str, object] = {}
# Cache schedule for a given (cal_name, year_month) key
_schedule_cache: dict[str, object] = {}


def _get_calendar(cal_name: str):
    """Return a cached calendar instance."""
    if not _HAS_MCAL:
        return None
    if cal_name not in _calendar_cache:
        try:
            _calendar_cache[cal_name] = mcal.get_calendar(cal_name)
        except Exception as exc:
            _log.warning("Could not load calendar %r: %s", cal_name, exc)
            _calendar_cache[cal_name] = None
    return _calendar_cache[cal_name]


def _get_schedule(cal_name: str, start: date, end: date):
    """Return a cached schedule DataFrame for the given date range."""
    if not _HAS_MCAL:
        return None
    key = f"{cal_name}:{start}:{end}"
    if key not in _schedule_cache:
        cal = _get_calendar(cal_name)
        if cal is None:
            _schedule_cache[key] = None
        else:
            try:
                _schedule_cache[key] = cal.schedule(
                    start_date=str(start), end_date=str(end)
                )
            except Exception as exc:
                _log.warning("schedule() failed for %r: %s", cal_name, exc)
                _schedule_cache[key] = None
    return _schedule_cache[key]


def _cal_name_for(symbol: str) -> str:
    return _SYMBOL_CALENDARS.get(symbol.upper(), _SYMBOL_CALENDARS["DEFAULT"])


def _get_holiday_name_from_cal(cal_name: str, for_date: date) -> Optional[str]:
    """Return the raw holiday name from the calendar for a given date, or None."""
    cal = _get_calendar(cal_name)
    if cal is None:
        return None
    try:
        rh = cal.regular_holidays
        start = str(for_date - timedelta(days=1))
        end   = str(for_date + timedelta(days=1))
        named = rh.holidays(start=start, end=end, return_name=True)
        for ts, name in named.items():
            if ts.date() == for_date:
                return _HOLIDAY_DISPLAY_NAMES.get(name, name)
    except Exception:
        pass
    return None


def _get_early_close_name(cal_name: str, for_date: date) -> Optional[str]:
    """Return (name, close_utc) if this is an early-close day, else None."""
    cal = _get_calendar(cal_name)
    if cal is None:
        return None
    try:
        sc = cal.special_closes
        for close_time_et, hcal in sc:
            named = hcal.holidays(
                start=str(for_date - timedelta(days=1)),
                end=str(for_date + timedelta(days=1)),
                return_name=True,
            )
            for ts, name in named.items():
                if ts.date() == for_date:
                    return _HOLIDAY_DISPLAY_NAMES.get(name, name)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class MarketCalendar:
    """
    Stateless utility class for market open/closed/holiday queries.
    All methods work with UTC datetimes by default.
    """

    @staticmethod
    def is_market_open(symbol: str, dt: Optional[datetime] = None) -> bool:
        """
        Return True if the market for *symbol* is currently in a trading session.

        On weekends and full holidays this returns False.
        On early-close days this returns True until the early-close time,
        then False afterwards.
        """
        info = MarketCalendar.get_session_info(symbol, dt)
        return info["is_open"]

    @staticmethod
    def is_holiday(symbol: str, dt: Optional[datetime] = None) -> bool:
        """Return True if today is a full market holiday (not weekend, not early-close)."""
        info = MarketCalendar.get_session_info(symbol, dt)
        return info["is_holiday"]

    @staticmethod
    def get_holiday_name(symbol: str, dt: Optional[datetime] = None) -> Optional[str]:
        """Return the holiday name if today is a holiday or early-close day, else None."""
        info = MarketCalendar.get_session_info(symbol, dt)
        return info.get("holiday_name")

    @staticmethod
    def next_open(symbol: str, dt: Optional[datetime] = None) -> Optional[datetime]:
        """Return the UTC datetime of the next market open, or None if already open."""
        info = MarketCalendar.get_session_info(symbol, dt)
        return info.get("next_open_utc")

    @staticmethod
    def get_upcoming_holidays(symbol: str, days: int = 60) -> list[dict]:
        """
        Return a list of upcoming holidays / early-close days for *symbol*
        within the next *days* calendar days.

        Each entry: {"date": "YYYY-MM-DD", "name": str, "type": "holiday"|"early_close",
                     "early_close_utc": Optional[str]}
        """
        if not _HAS_MCAL:
            return []

        cal_name = _cal_name_for(symbol)
        today = date.today()
        end   = today + timedelta(days=days)

        # Full holidays
        result: list[dict] = []
        cal = _get_calendar(cal_name)
        if cal is None:
            return []

        try:
            rh = cal.regular_holidays
            named = rh.holidays(start=str(today), end=str(end), return_name=True)
            for ts, raw_name in named.items():
                d = ts.date()
                if d >= today:
                    result.append({
                        "date": str(d),
                        "name": _HOLIDAY_DISPLAY_NAMES.get(raw_name, raw_name),
                        "type": "holiday",
                        "early_close_utc": None,
                    })
        except Exception as exc:
            _log.debug("regular holidays lookup failed: %s", exc)

        # Early-close days (not already in full holiday list)
        holiday_dates = {item["date"] for item in result}
        try:
            sched = _get_schedule(cal_name, today, end)
            if sched is not None:
                ec_df = cal.early_closes(sched)
                for idx, row in ec_df.iterrows():
                    d = idx.date()
                    if d < today or str(d) in holiday_dates:
                        continue
                    ec_name = _get_early_close_name(cal_name, d) or "Early Close"
                    result.append({
                        "date": str(d),
                        "name": ec_name,
                        "type": "early_close",
                        "early_close_utc": row["market_close"].isoformat(),
                    })
        except Exception as exc:
            _log.debug("early closes lookup failed: %s", exc)

        result.sort(key=lambda x: x["date"])
        return result

    @staticmethod
    def get_session_info(symbol: str, dt: Optional[datetime] = None) -> dict:
        """
        Return a comprehensive dict describing current market state for *symbol*.

        Keys:
            symbol          — canonicalized symbol string
            is_open         — bool: currently in a trading session
            is_weekend      — bool: today is Saturday or Sunday (no session started)
            is_holiday      — bool: today is a full CME holiday (weekday, no session)
            is_early_close  — bool: today closes early
            holiday_name    — str or None: e.g. "Good Friday", "Memorial Day"
            early_close_utc — ISO str or None: UTC datetime of early close
            market_open_utc — ISO str or None: when today's session opened
            market_close_utc— ISO str or None: when today's session closes/closed
            next_open_utc   — datetime or None: UTC of next session open (when closed)
            next_open_label — str: human label e.g. "Mon 18:00 UTC"
            reason          — str: plain English reason for current state
        """
        if dt is None:
            dt = datetime.now(timezone.utc)

        # Normalise to UTC-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        today_utc = dt.date()
        cal_name  = _cal_name_for(symbol)

        # Fallback when library unavailable
        if not _HAS_MCAL:
            return _always_open_result(symbol, dt)

        # Fetch schedule for a window: yesterday → today+90d
        window_start = today_utc - timedelta(days=1)
        window_end   = today_utc + timedelta(days=90)
        sched = _get_schedule(cal_name, window_start, window_end)

        if sched is None or len(sched) == 0:
            return _always_open_result(symbol, dt)

        # Is today a weekend?
        is_weekend = today_utc.weekday() >= 5  # 5=Sat, 6=Sun

        # Is today in the schedule (i.e. a trading day)?
        today_str = str(today_utc)
        today_in_sched = today_str in [str(d.date()) for d in sched.index]

        # --------------- current session row ---------------
        session_row = None
        for idx, row in sched.iterrows():
            if str(idx.date()) == today_str:
                session_row = row
                break

        is_holiday     = (not is_weekend) and (not today_in_sched)
        holiday_name   = None
        if is_holiday:
            holiday_name = _get_holiday_name_from_cal(cal_name, today_utc) or "Market Holiday"

        is_early_close  = False
        early_close_utc = None
        ec_name         = None
        market_open_utc = None
        market_close_utc = None

        if session_row is not None:
            market_open_utc  = session_row["market_open"]
            market_close_utc = session_row["market_close"]

            # Detect early close: close time significantly before 21:00 UTC (normal gold close)
            normal_close_hour = 20   # accept 20:xx–22:xx as normal
            close_h = market_close_utc.hour
            if close_h <= 19:
                is_early_close = True
                early_close_utc = market_close_utc.isoformat()
                ec_name = _get_early_close_name(cal_name, today_utc) or "Early Close"
                if ec_name:
                    holiday_name = ec_name

        # Are we inside an active session right now?
        is_open = False
        if session_row is not None:
            open_ts  = market_open_utc
            close_ts = market_close_utc
            is_open  = (open_ts <= dt < close_ts)

        # --------------- next open ---------------
        next_open_utc = None
        next_open_label = ""
        if not is_open:
            # Walk forward through schedule to find first row with open time > dt
            for idx, row in sched.iterrows():
                candidate_open = row["market_open"]
                if candidate_open > dt:
                    next_open_utc = candidate_open.to_pydatetime()
                    # Label: "Mon 18:00 UTC" or "Tomorrow 18:00 UTC" etc.
                    next_open_label = _format_next_open(next_open_utc, dt)
                    break

        # --------------- reason string ---------------
        if is_open:
            if is_early_close:
                reason = f"Open — early close today ({holiday_name})"
            else:
                reason = "Open"
        elif is_weekend:
            reason = f"Weekend — resumes {next_open_label}"
        elif is_holiday:
            reason = f"Market Holiday: {holiday_name} — resumes {next_open_label}"
        elif session_row is not None and dt >= market_close_utc:
            # Weekday, session ended for the day (e.g. after 21:00 UTC on weekday)
            reason = f"Session ended — next open {next_open_label}"
        elif session_row is not None and dt < market_open_utc:
            reason = f"Pre-session — opens {next_open_label}"
        else:
            reason = f"Closed — next open {next_open_label}"

        return {
            "symbol":          symbol.upper(),
            "calendar":        cal_name,
            "is_open":         is_open,
            "is_weekend":      is_weekend,
            "is_holiday":      is_holiday,
            "is_early_close":  is_early_close,
            "holiday_name":    holiday_name,
            "early_close_utc": early_close_utc,
            "market_open_utc": market_open_utc.isoformat() if market_open_utc is not None else None,
            "market_close_utc": market_close_utc.isoformat() if market_close_utc is not None else None,
            "next_open_utc":   next_open_utc,
            "next_open_label": next_open_label,
            "reason":          reason,
            "as_of_utc":       dt.isoformat(),
        }

    @staticmethod
    def format_closure_message(symbol: str, dt: Optional[datetime] = None) -> str:
        """
        Return a short human-readable message for the current closed state.
        E.g.  "Market holiday: Good Friday — opens Mon 18:00 UTC"
              "Weekend — XAUUSD opens Sun 18:00 UTC"
              "Market open" (if open)
        """
        info = MarketCalendar.get_session_info(symbol, dt)
        if info["is_open"]:
            return f"{symbol.upper()} market is open"
        return info["reason"]

    @staticmethod
    def suppress_stale_feed_error(symbol: str, dt: Optional[datetime] = None) -> bool:
        """
        Return True when a feed-staleness or data-gap error should be suppressed
        because the market is legitimately closed (weekend, holiday, between sessions).
        """
        info = MarketCalendar.get_session_info(symbol, dt)
        return not info["is_open"]

    @staticmethod
    def market_status_summary(symbols: Optional[list[str]] = None) -> dict:
        """
        Return a summary dict for multiple symbols.
        Default symbols: XAUUSD, NQ, US30, EURUSD
        """
        if symbols is None:
            symbols = ["XAUUSD", "NQ", "US30", "EURUSD"]

        out: dict[str, dict] = {}
        for sym in symbols:
            info = MarketCalendar.get_session_info(sym)
            out[sym] = {
                "is_open":      info["is_open"],
                "reason":       info["reason"],
                "is_holiday":   info["is_holiday"],
                "holiday_name": info["holiday_name"],
                "next_open":    info["next_open_label"],
            }
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_next_open(next_open: datetime, now: datetime) -> str:
    """Return e.g. 'Mon 18:00 UTC', 'Tomorrow 18:00 UTC', 'Today 18:00 UTC'."""
    delta = next_open.date() - now.date()
    time_str = next_open.strftime("%H:%M UTC")
    if delta.days == 0:
        return f"Today {time_str}"
    elif delta.days == 1:
        return f"Tomorrow {time_str}"
    else:
        day_name = next_open.strftime("%a")
        return f"{day_name} {time_str}"


def _always_open_result(symbol: str, dt: datetime) -> dict:
    """Fallback when pandas_market_calendars is unavailable."""
    return {
        "symbol":          symbol.upper(),
        "calendar":        "unknown",
        "is_open":         True,
        "is_weekend":      False,
        "is_holiday":      False,
        "is_early_close":  False,
        "holiday_name":    None,
        "early_close_utc": None,
        "market_open_utc": None,
        "market_close_utc": None,
        "next_open_utc":   None,
        "next_open_label": "unknown",
        "reason":          "Open (calendar library unavailable)",
        "as_of_utc":       dt.isoformat(),
    }
