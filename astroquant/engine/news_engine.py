import requests
import datetime
import xml.etree.ElementTree as ET


HIGH_IMPACT_KEYWORDS = ["CPI", "NFP", "FOMC", "Rate", "Powell"]


def is_high_impact(news_title):
    title = str(news_title or "")
    return any(word.lower() in title.lower() for word in HIGH_IMPACT_KEYWORDS)


class NewsEngine:

    def __init__(self):
        self.events = []
        self.last_fetch = None
        self.alerted_events = set()
        self.freeze_pre_minutes = 20
        self.freeze_post_minutes = 20

    def fetch_news(self):
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            root = ET.fromstring(response.content)

            self.events = []

            for item in root.findall("event"):
                impact_node = item.find("impact")
                currency_node = item.find("currency")
                date_node = item.find("date")
                time_node = item.find("time")
                title_node = item.find("title")

                impact = (impact_node.text or "").strip() if impact_node is not None else ""
                currency = (currency_node.text or "").strip() if currency_node is not None else ""
                date_str = (date_node.text or "").strip() if date_node is not None else ""
                time_str = (time_node.text or "").strip() if time_node is not None else ""
                title = (title_node.text or "").strip() if title_node is not None else ""

                if impact != "High":
                    continue

                if time_str in {"All Day", "Tentative", ""}:
                    continue

                try:
                    event_time = datetime.datetime.strptime(
                        date_str + " " + time_str,
                        "%m-%d-%Y %I:%M%p"
                    ).replace(tzinfo=datetime.UTC)
                except Exception:
                    continue

                self.events.append({
                    "title": title,
                    "currency": currency,
                    "impact": impact,
                    "time": event_time
                })

            self.last_fetch = datetime.datetime.now(datetime.UTC)

        except Exception as error:
            print("News fetch error:", error)

    def normalize_symbol(self, symbol):
        if symbol == "XAUUSD":
            return ["USD"]
        if symbol == "EURUSD":
            return ["EUR", "USD"]
        if symbol in ["NQ", "US30", "BTC"]:
            return ["USD"]
        return []

    def is_high_impact_near(self, symbol):
        now = datetime.datetime.now(datetime.UTC)
        currencies = self.normalize_symbol(symbol)
        freeze_pre = int(self.freeze_pre_minutes)
        freeze_post = int(self.freeze_post_minutes)

        for event in self.events:
            delta = (event["time"] - now).total_seconds()

            # freeze window: N minutes before to N minutes after
            if -(freeze_post * 60) <= delta <= (freeze_pre * 60):
                if event["currency"] in currencies:
                    return True, event["title"]

        return False, None

    def is_post_news_volatility(self, symbol):
        now = datetime.datetime.now(datetime.UTC)
        currencies = self.normalize_symbol(symbol)

        for event in self.events:
            if event.get("impact") != "High":
                continue
            if event.get("currency") not in currencies:
                continue

            delta = (now - event["time"]).total_seconds()
            if 600 < delta <= 1800:  # 10-30 minutes after event
                return True, event["title"]

        return False, None

    def news_risk_mode(self, symbol):
        now = datetime.datetime.now(datetime.UTC)
        currencies = self.normalize_symbol(symbol)
        freeze_pre = int(self.freeze_pre_minutes)
        freeze_post = int(self.freeze_post_minutes)

        for event in self.events:
            if event.get("currency") not in currencies:
                continue

            delta = (event["time"] - now).total_seconds()

            # During freeze window ±N min
            if -(freeze_post * 60) <= delta <= (freeze_pre * 60):
                return "HALT", event["title"]

            # Optional reduced-risk outside hard freeze but still near event
            if (freeze_pre * 60) < delta <= ((freeze_pre + 10) * 60):
                return "REDUCE_RISK", event["title"]

        return "NORMAL", None

    def high_impact_halt(self, symbol, minutes_to_news=15):
        now = datetime.datetime.now(datetime.UTC)
        currencies = self.normalize_symbol(symbol)
        freeze_pre = max(int(minutes_to_news), int(self.freeze_pre_minutes))
        freeze_post = int(self.freeze_post_minutes)

        for event in self.events:
            if event.get("currency") not in currencies:
                continue
            if not is_high_impact(event.get("title", "")):
                continue

            delta_minutes = (event["time"] - now).total_seconds() / 60.0
            if -float(freeze_post) <= delta_minutes <= float(freeze_pre):
                return True, event.get("title"), round(delta_minutes, 1)

        return False, None, None

    def check_and_alert(self, telegram):
        if not telegram:
            return

        now = datetime.datetime.now(datetime.UTC)

        for event in self.events:
            delta = (event["time"] - now).total_seconds()

            if 540 <= delta <= 600:  # 10 min before
                event_key = f"{event.get('title')}|{event.get('currency')}|{event.get('time')}"
                if event_key in self.alerted_events:
                    continue

                telegram.send_news_alert(event)
                self.alerted_events.add(event_key)
