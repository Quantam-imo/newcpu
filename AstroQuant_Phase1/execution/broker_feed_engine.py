import copy
import datetime
import os
import re
import time


class BrokerFeedEngine:

    PRICE_SELECTORS = {
        "bid": [
            "[data-testid='order-panel-sell-button']",
            "[data-testid='quote-bid']",
            "[data-testid='bid']",
            "[data-testid='order-book-bid']",
        ],
        "ask": [
            "[data-testid='order-panel-buy-button']",
            "[data-testid='quote-ask']",
            "[data-testid='ask']",
            "[data-testid='order-book-ask']",
        ],
    }

    ACCOUNT_SELECTORS = {
        "balance": ["[data-testid='balance-value']", "[data-testid='account-balance']"],
        "equity": ["[data-testid='equity-value']", "[data-testid='account-equity']"],
        "free_margin": ["[data-testid='free-margin-value']", "[data-testid='account-free-margin']"],
        "daily_pnl": ["[data-testid='daily-pnl-value']", "[data-testid='account-daily-pnl']"],
        "open_risk": ["[data-testid='open-risk-value']", "[data-testid='account-open-risk']"],
    }

    POSITION_ROW_SELECTOR = "[data-testid='position-row']"

    def __init__(self):
        self.freeze_seconds = max(2, int(float(os.getenv("BROKER_PRICE_FREEZE_SECONDS", "8"))))
        self.ui_profile = str(os.getenv("BROKER_UI_PROFILE", "maven-matchtrader")).strip().lower()
        self._last_price = None
        self._last_price_change_at = None
        self._last_url = None

        self._state = {
            "price": {
                "symbol": "XAUUSD",
                "bid": None,
                "ask": None,
                "mid": None,
                "spread": None,
                "extraction_source": None,
                "timestamp": None,
            },
            "account": {
                "balance": None,
                "equity": None,
                "free_margin": None,
                "daily_pnl": None,
                "open_risk": None,
                "timestamp": None,
            },
            "positions": {
                "open_count": 0,
                "rows": [],
                "empty_state": True,
                "timestamp": None,
            },
            "health": {
                "dom_ok": False,
                "price_frozen": False,
                "page_changed": False,
                "kill_switch": True,
                "reasons": ["Broker feed not initialized"],
                "updated_at": None,
            },
        }

    @staticmethod
    def _utc_now_iso():
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    @staticmethod
    def _normalize_numeric_text(text):
        if text is None:
            return ""
        cleaned = str(text).replace("\u00A0", " ").replace(",", "")
        cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned)
        return cleaned

    @staticmethod
    def _safe_float(value):
        if value is None:
            return None
        text = BrokerFeedEngine._normalize_numeric_text(value).strip()
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            return float(match.group(0))
        except Exception:
            return None

    @staticmethod
    def _read_text(page, selectors):
        for selector in selectors:
            try:
                node = page.query_selector(selector)
                if not node:
                    continue
                value = node.inner_text()
                if value and str(value).strip():
                    return str(value).strip()
            except Exception:
                continue
        return None

    @staticmethod
    def _extract_number(text):
        if text is None:
            return None
        normalized = BrokerFeedEngine._normalize_numeric_text(text)
        match = re.search(r"-?\d+(?:\.\d+)?", normalized)
        if not match:
            return None
        try:
            return float(match.group(0))
        except Exception:
            return None

    @staticmethod
    def _extract_label_number(blob, label):
        if not blob:
            return None
        pattern = rf"{re.escape(label)}\s*[:]?\s*(-?\d[\d\s,]*(?:\.\d+)?)"
        match = re.search(pattern, str(blob), flags=re.IGNORECASE)
        if not match:
            return None
        try:
            normalized = BrokerFeedEngine._normalize_numeric_text(match.group(1))
            return float(normalized)
        except Exception:
            return None

    @staticmethod
    def _extract_chart_symbol(blob):
        if not blob:
            return None
        match = re.search(r"\b([A-Z]{3,10})\s+(?:O|H|L|C)\s*-?\d", str(blob))
        if match:
            return str(match.group(1)).upper()
        return None

    @staticmethod
    def _symbol_in_body(blob, symbol):
        if not blob or not symbol:
            return False
        return re.search(rf"\b{re.escape(str(symbol).upper())}\b", str(blob).upper()) is not None

    def _capture_price(self, page, symbol):
        try:
            body_text = page.inner_text("body")
        except Exception:
            body_text = ""

        source_tags = []

        effective_symbol = symbol
        inferred_symbol = self._extract_chart_symbol(body_text)
        if inferred_symbol:
            effective_symbol = inferred_symbol
            source_tags.append("chart_symbol")

        bid_text = self._read_text(page, self.PRICE_SELECTORS["bid"])
        ask_text = self._read_text(page, self.PRICE_SELECTORS["ask"])

        bid = self._extract_number(bid_text)
        ask = self._extract_number(ask_text)
        if bid is not None or ask is not None:
            source_tags.append("dom")

        # Maven/Match-Trader fallback from full page text when button selector parsing fails.
        if self.ui_profile == "maven-matchtrader" and (bid is None or ask is None):
            def _extract_symbol_local_pair(target_symbol):
                if not target_symbol:
                    return (None, None)
                match = re.search(re.escape(target_symbol), body_text, flags=re.IGNORECASE)
                if not match:
                    return (None, None)

                window = body_text[match.start(): match.start() + 5000]

                def _side_from_window(side):
                    patterns = [
                        rf"{side}\s+(-?\d+(?:\.\d+)?)",
                        rf"{side}\s+LIMIT\s+(-?\d+(?:\.\d+)?)",
                        rf"{side}\s+STOP\s+(-?\d+(?:\.\d+)?)",
                    ]
                    for pattern in patterns:
                        matched = re.search(pattern, window, flags=re.IGNORECASE)
                        if matched:
                            return self._extract_number(matched.group(1))
                    return None

                return (_side_from_window("SELL"), _side_from_window("BUY"))

            def _extract_symbol_scoped_price(target_symbol, side):
                if not target_symbol:
                    return None
                symbol_patterns = [
                    rf"{re.escape(target_symbol)}[\s\S]{{0,1200}}?{side}\s+(-?\d+(?:\.\d+)?)",
                    rf"{re.escape(target_symbol)}[\s\S]{{0,1200}}?{side}\s+LIMIT\s+(-?\d+(?:\.\d+)?)",
                    rf"{re.escape(target_symbol)}[\s\S]{{0,1200}}?{side}\s+STOP\s+(-?\d+(?:\.\d+)?)",
                ]
                for pattern in symbol_patterns:
                    matched = re.search(pattern, body_text, flags=re.IGNORECASE)
                    if matched:
                        return self._extract_number(matched.group(1))
                return None

            def _extract_side_price(side):
                candidates = [
                    rf"{side}\s+(-?\d+(?:\.\d+)?)",
                    rf"{side}\s+LIMIT\s+(-?\d+(?:\.\d+)?)",
                    rf"{side}\s+STOP\s+(-?\d+(?:\.\d+)?)",
                ]
                for pattern in candidates:
                    matched = re.search(pattern, body_text, flags=re.IGNORECASE)
                    if matched:
                        return self._extract_number(matched.group(1))
                return None

            local_bid, local_ask = _extract_symbol_local_pair(effective_symbol)

            if bid is None:
                if local_bid is not None:
                    bid = local_bid
                    source_tags.append("symbol_local")
                else:
                    scoped_bid = _extract_symbol_scoped_price(effective_symbol, "SELL")
                    if scoped_bid is not None:
                        bid = scoped_bid
                        source_tags.append("symbol_scoped")
                    else:
                        generic_bid = _extract_side_price("SELL")
                        if generic_bid is not None:
                            bid = generic_bid
                            source_tags.append("generic_side")
            if ask is None:
                if local_ask is not None:
                    ask = local_ask
                    source_tags.append("symbol_local")
                else:
                    scoped_ask = _extract_symbol_scoped_price(effective_symbol, "BUY")
                    if scoped_ask is not None:
                        ask = scoped_ask
                        source_tags.append("symbol_scoped")
                    else:
                        generic_ask = _extract_side_price("BUY")
                        if generic_ask is not None:
                            ask = generic_ask
                            source_tags.append("generic_side")

            # Pending tab fallback: use "Price" field when both side quotes are not available.
            if bid is None and ask is None:
                pending_price = self._extract_label_number(body_text, "Price")
                if pending_price is not None:
                    bid = float(pending_price)
                    ask = float(pending_price)
                    source_tags.append("pending_price")

        panel_spread = None
        if self.ui_profile == "maven-matchtrader":
            try:
                body_text = page.inner_text("body")
            except Exception:
                body_text = ""
            panel_spread = self._extract_label_number(body_text, "Spread")

        mid = None
        spread = None
        if bid is not None and ask is not None:
            mid = round((bid + ask) / 2.0, 5)
            spread = round(max(0.0, ask - bid), 5)
        elif panel_spread is not None:
            spread = round(max(0.0, float(panel_spread)), 5)

        extraction_source = "+".join(sorted(set(source_tags))) if source_tags else "unknown"

        return {
            "symbol": effective_symbol,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": spread,
            "extraction_source": extraction_source,
            "timestamp": self._utc_now_iso(),
        }

    def _capture_account(self, page):
        result = {"timestamp": self._utc_now_iso()}
        for key, selectors in self.ACCOUNT_SELECTORS.items():
            text = self._read_text(page, selectors)
            result[key] = self._safe_float(text)

        # Maven/Match-Trader screenshot-driven fallback parsing.
        try:
            body_text = page.inner_text("body")
        except Exception:
            body_text = ""

        if result.get("daily_pnl") is None:
            result["daily_pnl"] = self._extract_label_number(body_text, "Profit")
        if result.get("balance") is None:
            result["balance"] = self._extract_label_number(body_text, "Balance")
        if result.get("equity") is None:
            result["equity"] = self._extract_label_number(body_text, "Equity")
        if result.get("free_margin") is None:
            result["free_margin"] = self._extract_label_number(body_text, "Free margin")
        if result.get("free_margin") is None:
            result["free_margin"] = self._extract_label_number(body_text, "Free funds")
        if result.get("open_risk") is None:
            result["open_risk"] = self._extract_label_number(body_text, "Open risk")
        if result.get("open_risk") is None:
            result["open_risk"] = self._extract_label_number(body_text, "Required margin")

        result["commission"] = self._extract_label_number(body_text, "Commission")
        result["panel_spread"] = self._extract_label_number(body_text, "Spread")

        if result.get("equity") is None and result.get("balance") is not None and result.get("daily_pnl") is not None:
            result["equity"] = round(float(result["balance"]) + float(result["daily_pnl"]), 5)

        return result

    def _capture_positions(self, page):
        rows = []
        empty_state = False
        try:
            try:
                page.click("[data-testid='open-positions-tab']")
            except Exception:
                pass

            position_rows = page.query_selector_all(self.POSITION_ROW_SELECTOR)
            for row in position_rows:
                try:
                    rows.append({"raw": row.inner_text().strip()})
                except Exception:
                    continue

            if not rows:
                try:
                    body_text = page.inner_text("body")
                except Exception:
                    body_text = ""
                empty_state = "don't have any open positions" in body_text.lower()
        except Exception:
            rows = []

        return {
            "open_count": len(rows),
            "rows": rows,
            "empty_state": empty_state,
            "timestamp": self._utc_now_iso(),
        }

    def _build_health(self, page, price_state):
        reasons = []
        dom_ok = bool(price_state.get("bid") is not None and price_state.get("ask") is not None)
        if not dom_ok:
            reasons.append("Missing bid/ask DOM")

        current_url = None
        try:
            current_url = str(getattr(page, "url", "") or "")
        except Exception:
            current_url = None

        page_changed = False
        if self._last_url and current_url and current_url != self._last_url:
            page_changed = True
            reasons.append("Page URL changed")
        self._last_url = current_url or self._last_url

        current_price = (price_state.get("bid"), price_state.get("ask"))
        now = time.time()
        if current_price != self._last_price:
            self._last_price = current_price
            self._last_price_change_at = now

        freeze_anchor = self._last_price_change_at or now
        price_frozen = (now - freeze_anchor) > self.freeze_seconds
        if price_frozen:
            reasons.append("Price feed frozen")

        kill_switch = (not dom_ok) or price_frozen or page_changed
        if not reasons:
            reasons = ["OK"]

        return {
            "dom_ok": dom_ok,
            "price_frozen": price_frozen,
            "page_changed": page_changed,
            "kill_switch": kill_switch,
            "reasons": reasons,
            "updated_at": self._utc_now_iso(),
        }

    def update(self, page, symbol="XAUUSD"):
        if page is None:
            self._state["health"] = {
                "dom_ok": False,
                "price_frozen": False,
                "page_changed": False,
                "kill_switch": True,
                "reasons": ["Browser page unavailable"],
                "updated_at": self._utc_now_iso(),
            }
            return copy.deepcopy(self._state)

        price_state = self._capture_price(page, symbol)
        account_state = self._capture_account(page)
        positions_state = self._capture_positions(page)
        health_state = self._build_health(page, price_state)

        self._state["price"] = price_state
        self._state["account"] = account_state
        self._state["positions"] = positions_state
        self._state["health"] = health_state
        return copy.deepcopy(self._state)

    def get_state(self):
        return copy.deepcopy(self._state)
