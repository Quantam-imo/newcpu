import databento as db
import datetime
import time
import re
import threading
from collections import defaultdict

try:
    import databento_dbn as dbn
except Exception:
    dbn = None


class MarketFeed:

    def __init__(self, api_key):
        self.api_key = api_key
        self.last_error = None
        self.client = db.Historical(api_key) if api_key else None
        self.auth_failed_until = 0.0
        self.auth_cooldown_seconds = 90.0
        self.auth_probe_interval_seconds = 20.0
        self.last_auth_probe_at = 0.0
        self.live_client = None
        self.live_lock = threading.Lock()
        self.live_started = False
        self.live_thread = None
        self.live_last_error = None
        self.live_prices = {}
        self.live_instrument_symbol = defaultdict(dict)
        self.live_subscriptions = set()
        self.live_streams = {}
        self.live_pending = set()

    def is_configured(self):
        return bool(self.api_key)

    def health(self):
        if not self.is_configured():
            return {
                "configured": False,
                "healthy": False,
                "reason": "Missing DATABENTO_API_KEY",
                "last_error": self.last_error,
                "auth_cooldown_seconds": 0,
            }
        cooldown = max(0, int(self.auth_failed_until - time.time()))
        last_error_text = str(self.last_error or "")
        symbol_resolution_only = "symbology_invalid_request" in last_error_text.lower()
        live_active = bool(self.live_streams) or bool(self.live_started)
        reason = "OK"
        if cooldown > 0:
            reason = "Authentication degraded (cache/live fallback active)" if live_active else "Authentication failed"
        elif self.last_error is not None:
            if symbol_resolution_only and live_active:
                reason = "Symbol fallback active"
            else:
                reason = "Feed error"
        healthy_now = (cooldown <= 0) and (
            self.last_error is None
            or (symbol_resolution_only and live_active)
        )
        return {
            "configured": True,
            "healthy": healthy_now,
            "reason": reason,
            "last_error": self.last_error,
            "auth_cooldown_seconds": cooldown,
            "live_started": bool(self.live_streams),
            "live_last_error": self.live_last_error,
        }

    def test_connection(self, dataset, symbol):
        candles = self.get_ohlcv(dataset, symbol)
        return {
            "configured": self.is_configured(),
            "healthy": len(candles) > 0,
            "candles": len(candles),
            "last_error": self.last_error,
            "auth_cooldown_seconds": max(0, int(self.auth_failed_until - time.time())),
        }

    def _is_auth_error(self, error_text):
        text = str(error_text or "").lower()
        return "auth_authentication_failed" in text or "authentication failed" in text or "401" in text

    def _extract_available_end(self, error_text):
        text = str(error_text or "")
        if "data_end_after_available_end" not in text:
            return None
        match = re.search(r"available up to '([^']+)'", text)
        if not match:
            return None
        raw_ts = str(match.group(1)).strip()
        try:
            normalized = raw_ts.replace(" ", "T")
            if normalized.endswith("+00:00"):
                return datetime.datetime.fromisoformat(normalized)
            if normalized.endswith("Z"):
                return datetime.datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            return datetime.datetime.fromisoformat(normalized)
        except Exception:
            return None

    def _row_time_seconds(self, row):
        raw = getattr(row, "ts_event", None)
        if raw is None:
            return int(time.time())
        if hasattr(raw, "timestamp"):
            return int(raw.timestamp())
        try:
            value = int(raw)
            if value > 10_000_000_000_000:
                return int(value / 1_000_000_000)
            if value > 10_000_000_000:
                return int(value / 1_000_000)
            return value
        except Exception:
            return int(time.time())

    def _normalize_price(self, value):
        try:
            numeric = float(value)
        except Exception:
            return value
        if abs(numeric) >= 1_000_000_000:
            return numeric / 1_000_000_000.0
        return numeric

    def _quote_key(self, dataset, symbol, stype_in):
        return (
            str(dataset or "").strip().upper(),
            str(symbol or "").strip(),
            str(stype_in or "raw_symbol").strip().lower(),
        )

    def _ensure_live_started(self):
        if not self.api_key:
            return False
        with self.live_lock:
            if self.live_client is None:
                try:
                    self.live_client = db.Live(key=self.api_key, reconnect_policy="reconnect")
                    self.live_client.add_callback(self._on_live_record, self._on_live_callback_error)
                    self.live_client.add_reconnect_callback(self._on_live_reconnect)
                except Exception as exc:
                    self.live_last_error = str(exc)
                    self.live_client = None
                    return False

            if self.live_started:
                return True

            try:
                self.live_client.start()
                self.live_started = True
            except Exception as exc:
                self.live_last_error = str(exc)
                self.live_started = False
                return False

            if self.live_thread is None or not self.live_thread.is_alive():
                self.live_thread = threading.Thread(target=self._live_wait_loop, daemon=True)
                self.live_thread.start()
            return True

    def _live_wait_loop(self):
        client = self.live_client
        if client is None:
            return
        try:
            client.block_for_close(timeout=None)
        except Exception as exc:
            self.live_last_error = str(exc)
        finally:
            with self.live_lock:
                self.live_started = False

    def _on_live_callback_error(self, exc):
        self.live_last_error = str(exc)

    def _on_live_reconnect(self):
        self.live_last_error = None

    def _resolve_live_symbol(self, dataset, record):
        instrument_id = getattr(record, "instrument_id", None)
        if instrument_id is None:
            return None
        bucket = self.live_instrument_symbol.get(str(dataset or "").strip().upper(), {})
        symbol = bucket.get(int(instrument_id))
        return str(symbol) if symbol else None

    def _extract_live_price(self, record):
        for field in ("price", "close", "last", "px", "px_last"):
            if hasattr(record, field):
                raw = getattr(record, field)
                try:
                    return self._normalize_price(raw)
                except Exception:
                    continue
        bid = getattr(record, "bid_px", None)
        ask = getattr(record, "ask_px", None)
        if bid is not None and ask is not None:
            try:
                return (self._normalize_price(bid) + self._normalize_price(ask)) / 2.0
            except Exception:
                return None
        return None

    def _on_live_record(self, record):
        try:
            if dbn is not None and isinstance(record, dbn.SymbolMappingMsg):
                dataset = str(getattr(self.live_client, "dataset", "") or "").strip().upper()
                instrument_id = int(getattr(record, "instrument_id", 0) or 0)
                stype_symbol = str(getattr(record, "stype_in_symbol", "") or "").strip()
                if dataset and instrument_id and stype_symbol:
                    self.live_instrument_symbol[dataset][instrument_id] = stype_symbol
                return

            dataset = str(getattr(self.live_client, "dataset", "") or "").strip().upper()
            symbol = self._resolve_live_symbol(dataset, record)
            if not symbol:
                return

            price = self._extract_live_price(record)
            if price is None:
                return

            ts = self._row_time_seconds(record)
            now = int(time.time())
            with self.live_lock:
                for stype in ("raw_symbol", "continuous", "parent"):
                    self.live_prices[self._quote_key(dataset, symbol, stype)] = {
                        "price": float(price),
                        "time": ts if ts > 0 else now,
                        "updated_at": now,
                        "dataset": dataset,
                        "symbol": symbol,
                        "source": "DATABENTO_LIVE",
                    }
            self.live_last_error = None
        except Exception as exc:
            self.live_last_error = str(exc)

    def ensure_live_subscription(self, dataset, symbol, stype_in="raw_symbol"):
        if not self.api_key:
            return False
        key = self._quote_key(dataset, symbol, stype_in)
        with self.live_lock:
            if key in self.live_streams:
                return True

        stream_client = None
        stream_thread = None

        try:
            stream_client = db.Live(key=self.api_key, reconnect_policy="reconnect")

            def _record_callback(record, quote_key=key, source_symbol=str(symbol), source_dataset=str(dataset).strip().upper()):
                try:
                    price = self._extract_live_price(record)
                    if price is None:
                        return
                    ts = self._row_time_seconds(record)
                    now = int(time.time())
                    with self.live_lock:
                        self.live_prices[quote_key] = {
                            "price": float(price),
                            "time": ts if ts > 0 else now,
                            "updated_at": now,
                            "dataset": source_dataset,
                            "symbol": source_symbol,
                            "source": "DATABENTO_LIVE",
                        }
                    self.live_last_error = None
                except Exception as callback_exc:
                    self.live_last_error = str(callback_exc)

            def _exception_callback(exc):
                self.live_last_error = str(exc)

            stream_client.add_callback(_record_callback, _exception_callback)
            stream_client.subscribe(
                dataset=str(dataset),
                schema="trades",
                symbols=[str(symbol)],
                stype_in=str(stype_in or "raw_symbol"),
                start=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=3),
            )
            stream_client.start()

            stream_thread = threading.Thread(target=stream_client.block_for_close, kwargs={"timeout": None}, daemon=True)
            stream_thread.start()
        except Exception as exc:
            self.live_last_error = str(exc)
            if stream_client is not None:
                try:
                    stream_client.terminate()
                except Exception:
                    pass
            return False

        with self.live_lock:
            self.live_streams[key] = {
                "client": stream_client,
                "thread": stream_thread,
            }
            self.live_pending.discard(key)
            self.live_started = True
        return True

    def ensure_live_subscription_async(self, dataset, symbol, stype_in="raw_symbol"):
        key = self._quote_key(dataset, symbol, stype_in)
        with self.live_lock:
            if key in self.live_streams or key in self.live_pending:
                return
            self.live_pending.add(key)

        def worker():
            try:
                self.ensure_live_subscription(dataset=dataset, symbol=symbol, stype_in=stype_in)
            finally:
                with self.live_lock:
                    self.live_pending.discard(key)

        threading.Thread(target=worker, daemon=True).start()

    def get_live_quote(self, dataset, symbol, stype_in=None, max_age_seconds=20):
        if not dataset or not symbol:
            return None
        normalized_dataset = str(dataset).strip().upper()
        normalized_symbol = str(symbol).strip()
        stypes = [str(stype_in).strip().lower()] if stype_in else ["continuous", "parent", "raw_symbol"]
        now = int(time.time())

        with self.live_lock:
            for candidate_symbol in (normalized_symbol, normalized_symbol.upper(), normalized_symbol.lower()):
                for candidate_stype in stypes:
                    key = self._quote_key(normalized_dataset, candidate_symbol, candidate_stype)
                    quote = self.live_prices.get(key)
                    if not quote:
                        continue
                    updated_at = int(quote.get("updated_at", 0) or 0)
                    if (now - updated_at) > max(1, int(max_age_seconds or 20)):
                        continue
                    return dict(quote)
        return None

    def stop_live(self):
        with self.live_lock:
            streams = list(self.live_streams.values())
            self.live_streams = {}
            self.live_client = None
            self.live_started = False
            self.live_subscriptions.clear()
            self.live_instrument_symbol.clear()
            self.live_prices.clear()

        for stream in streams:
            client = stream.get("client")
            if client is None:
                continue
            try:
                client.stop()
            except Exception:
                pass
            try:
                client.terminate()
            except Exception:
                pass

    def get_ohlcv(self, dataset, symbol, lookback_minutes=60, stype_in=None, record_limit=None):
        if not self.client:
            self.last_error = "Missing DATABENTO_API_KEY"
            return []

        now_ts = time.time()
        if self.auth_failed_until > now_ts:
            if (now_ts - self.last_auth_probe_at) < max(3.0, float(self.auth_probe_interval_seconds)):
                if not self.last_error:
                    self.last_error = "Authentication failed"
                return []
            self.last_auth_probe_at = now_ts

        end = datetime.datetime.now(datetime.UTC)
        bounded_lookback = max(10, min(int(lookback_minutes or 60), 60 * 24 * 14))
        start = end - datetime.timedelta(minutes=bounded_lookback)

        candidate_stypes = []
        if stype_in:
            candidate_stypes = [stype_in]
        elif symbol.endswith(".FUT"):
            candidate_stypes = ["parent", "continuous", "raw_symbol"]
        elif ".c." in symbol:
            candidate_stypes = ["continuous", "parent", "raw_symbol"]
        else:
            candidate_stypes = ["raw_symbol", "parent"]

        bounded_record_limit = None
        if record_limit is not None:
            bounded_record_limit = max(100, min(int(record_limit), 10000))

        last_exc = None
        for candidate_stype in candidate_stypes:
            self.ensure_live_subscription_async(dataset=dataset, symbol=symbol, stype_in=candidate_stype)
            current_end = end
            current_start = start
            try:
                data = self.client.timeseries.get_range(
                    dataset=dataset,
                    schema="ohlcv-1m",
                    symbols=[symbol],
                    stype_in=candidate_stype,
                    start=current_start,
                    end=current_end,
                    limit=bounded_record_limit,
                )

                candles = []
                for row in data:
                    candles.append({
                        "time": self._row_time_seconds(row),
                        "open": self._normalize_price(row.open),
                        "high": self._normalize_price(row.high),
                        "low": self._normalize_price(row.low),
                        "close": self._normalize_price(row.close),
                        "volume": row.volume
                    })

                if candles:
                    self.auth_failed_until = 0.0
                    live_quote = self.get_live_quote(dataset=dataset, symbol=symbol, stype_in=candidate_stype, max_age_seconds=20)
                    if live_quote:
                        try:
                            live_price = float(live_quote.get("price"))
                            last = candles[-1]
                            last["close"] = live_price
                            last["high"] = max(float(last.get("high", live_price)), live_price)
                            last["low"] = min(float(last.get("low", live_price)), live_price)
                        except Exception:
                            pass
                    self.last_error = None
                    return candles
            except Exception as error:
                last_exc = error
                if self._is_auth_error(error):
                    self.auth_failed_until = time.time() + max(15.0, float(self.auth_cooldown_seconds))
                    self.last_auth_probe_at = time.time()
                    self.last_error = str(error)
                    return []
                self.auth_failed_until = 0.0
                available_end = self._extract_available_end(error)
                if available_end is not None:
                    try:
                        retry_end = available_end - datetime.timedelta(seconds=1)
                        retry_lookback = max(bounded_lookback, 180)
                        retry_start = retry_end - datetime.timedelta(minutes=retry_lookback)
                        retry_data = self.client.timeseries.get_range(
                            dataset=dataset,
                            schema="ohlcv-1m",
                            symbols=[symbol],
                            stype_in=candidate_stype,
                            start=retry_start,
                            end=retry_end,
                            limit=bounded_record_limit,
                        )
                        retry_candles = []
                        for row in retry_data:
                            retry_candles.append({
                                "time": self._row_time_seconds(row),
                                "open": self._normalize_price(row.open),
                                "high": self._normalize_price(row.high),
                                "low": self._normalize_price(row.low),
                                "close": self._normalize_price(row.close),
                                "volume": row.volume,
                            })
                        live_quote = self.get_live_quote(dataset=dataset, symbol=symbol, stype_in=candidate_stype, max_age_seconds=20)
                        if live_quote and retry_candles:
                            try:
                                live_price = float(live_quote.get("price"))
                                last = retry_candles[-1]
                                last["close"] = live_price
                                last["high"] = max(float(last.get("high", live_price)), live_price)
                                last["low"] = min(float(last.get("low", live_price)), live_price)
                            except Exception:
                                pass
                        self.last_error = None
                        return retry_candles
                    except Exception as retry_error:
                        last_exc = retry_error

        self.last_error = str(last_exc) if last_exc else None
        return []
