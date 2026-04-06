from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import databento as db


@dataclass
class FetchResult:
    symbol: str
    records: int
    start: datetime
    end: datetime
    fallback_used: bool
    reason: str
    dataframe: object


class AstroQuantFinalDataEngine:
    """
    Production-oriented Databento historical engine with:
    - symbol priority lists for GC and ES
    - safe end-time clamping
    - automatic retry for data_start_after_available_end
    - Friday-session fallback for empty windows
    """

    DEFAULT_GC_SYMBOLS = ["GC.c.1", "GCM6", "GCQ6", "GCZ6"]  # GCJ6 expired April 2026
    DEFAULT_ES_SYMBOLS = ["NQ.c.1", "NQM6", "NQU6"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        dataset: str = "GLBX.MDP3",
        schema: str = "trades",
        safety_lag_minutes: int = 30,
    ) -> None:
        self.api_key = api_key or os.getenv("DATABENTO_API_KEY")
        if not self.api_key:
            raise ValueError("DATABENTO_API_KEY is required")

        self.dataset = dataset
        self.schema = schema
        self.safety_lag_minutes = max(1, int(safety_lag_minutes))
        self.client = db.Historical(self.api_key)

    def safe_end(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(minutes=self.safety_lag_minutes)

    def clamp_window(self, start: datetime, end: datetime) -> Tuple[datetime, datetime]:
        safe_end = self.safe_end()
        end_clamped = min(end, safe_end)
        if start >= end_clamped:
            start = end_clamped - timedelta(minutes=30)
        return start, end_clamped

    def default_window(self, minutes: int = 60) -> Tuple[datetime, datetime]:
        end = self.safe_end()
        start = end - timedelta(minutes=max(1, int(minutes)))
        return start, end

    def _extract_available_end(self, err: Exception) -> Optional[datetime]:
        # Handles multiple Databento 422 formats, for example:
        # - available end of dataset ... ('2026-03-22 06:10:00+00:00')
        # - The dataset ... has data available up to '2026-03-22 06:10:00+00:00'
        text = str(err)
        patterns = [
            r"available end of dataset [^']+\('([^']+)'\)",
            r"data available up to '([^']+)'",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = str(match.group(1)).replace(" ", "T")
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                continue
        return None

    def _fetch_df(self, symbol: str, start: datetime, end: datetime):
        # Continuous contract symbols (e.g. "GC.c.1") need stype_in="continuous".
        # All other raw symbols (e.g. "GCM6") use the default raw_symbol stype.
        kwargs: dict = dict(
            dataset=self.dataset,
            schema=self.schema,
            symbols=[symbol],
            start=start,
            end=end,
        )
        if re.search(r"\.c\.\d+$", symbol):
            kwargs["stype_in"] = "continuous"
        data = self.client.timeseries.get_range(**kwargs)
        return data.to_df()

    def _session_fallback_windows(
        self, ref: Optional[datetime] = None
    ):
        """Yield narrow 3-hour session windows going back one calendar day at a time.

        Starting from ``ref`` the generator steps back up to 7 days.  Each
        window covers 18:00–21:00 UTC (the last active hours before CME gold /
        equity futures close).  Saturday windows are skipped immediately since
        CME is always closed Saturday.  Holidays (e.g. Good Friday) return 0
        rows from Databento, so the caller naturally falls through to the next
        window without any special holiday calendar needed.
        """
        ref = ref or self.safe_end()
        for days_back in range(1, 8):
            anchor = ref - timedelta(days=days_back)
            if anchor.weekday() == 5:  # Saturday — never any CME data
                continue
            d = anchor.date()
            yield (
                datetime(d.year, d.month, d.day, 18, 0, 0, tzinfo=timezone.utc),
                datetime(d.year, d.month, d.day, 21, 0, 0, tzinfo=timezone.utc),
            )

    def fetch_with_fallback(
        self,
        symbol_candidates: List[str],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        minutes: int = 60,
    ) -> FetchResult:
        if not symbol_candidates:
            raise ValueError("symbol_candidates must not be empty")

        if start is None or end is None:
            start, end = self.default_window(minutes=minutes)

        start, end = self.clamp_window(start, end)
        duration = max(timedelta(minutes=1), end - start)

        last_error = ""
        for symbol in symbol_candidates:
            try:
                df = self._fetch_df(symbol=symbol, start=start, end=end)
                if len(df) > 0:
                    return FetchResult(
                        symbol=symbol,
                        records=len(df),
                        start=start,
                        end=end,
                        fallback_used=False,
                        reason="primary_window",
                        dataframe=df,
                    )

                # Primary window empty (weekend / holiday): slide back day-by-day
                # using narrow 3-hour windows.  Each window is small so downloads are
                # fast; holidays return 0 rows and we naturally continue to the next day.
                for fb_start, fb_end in self._session_fallback_windows(ref=end):
                    try:
                        fb_df = self._fetch_df(symbol=symbol, start=fb_start, end=fb_end)
                        if len(fb_df) > 0:
                            return FetchResult(
                                symbol=symbol,
                                records=len(fb_df),
                                start=fb_start,
                                end=fb_end,
                                fallback_used=True,
                                reason="session_fallback_empty_primary",
                                dataframe=fb_df,
                            )
                    except Exception as fb_exc:
                        last_error = f"session_fallback_error={fb_exc}"

            except Exception as exc:
                last_error = str(exc)

                available_end = self._extract_available_end(exc)
                if available_end is not None:
                    # Retry once clamped to the API-reported available end.
                    retry_end = available_end - timedelta(seconds=1)
                    retry_start = retry_end - duration
                    try:
                        retry_df = self._fetch_df(symbol=symbol, start=retry_start, end=retry_end)
                        if len(retry_df) > 0:
                            return FetchResult(
                                symbol=symbol,
                                records=len(retry_df),
                                start=retry_start,
                                end=retry_end,
                                fallback_used=True,
                                reason="api_available_end_clamp",
                                dataframe=retry_df,
                            )
                    except Exception as retry_exc:
                        last_error = f"{last_error} | retry_error={retry_exc}"

                # Last resort: slide back day-by-day in narrow windows.
                for fb_start, fb_end in self._session_fallback_windows(ref=end):
                    try:
                        fb_df = self._fetch_df(symbol=symbol, start=fb_start, end=fb_end)
                        if len(fb_df) > 0:
                            return FetchResult(
                                symbol=symbol,
                                records=len(fb_df),
                                start=fb_start,
                                end=fb_end,
                                fallback_used=True,
                                reason="session_fallback_after_error",
                                dataframe=fb_df,
                            )
                    except Exception as fb_exc:
                        last_error = f"{last_error} | session_fallback_error={fb_exc}"

        raise RuntimeError(f"All symbol candidates failed: {symbol_candidates}. last_error={last_error}")

    def fetch_synced_gc_es(
        self,
        gc_symbols: Optional[List[str]] = None,
        es_symbols: Optional[List[str]] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        minutes: int = 60,
    ) -> Dict[str, FetchResult]:
        gc_symbols = gc_symbols or self.DEFAULT_GC_SYMBOLS
        es_symbols = es_symbols or self.DEFAULT_ES_SYMBOLS

        if start is None or end is None:
            start, end = self.default_window(minutes=minutes)

        start, end = self.clamp_window(start, end)

        gc = self.fetch_with_fallback(gc_symbols, start=start, end=end, minutes=minutes)
        es = self.fetch_with_fallback(es_symbols, start=start, end=end, minutes=minutes)

        return {"GC": gc, "ES": es}


def build_default_engine() -> AstroQuantFinalDataEngine:
    return AstroQuantFinalDataEngine()
