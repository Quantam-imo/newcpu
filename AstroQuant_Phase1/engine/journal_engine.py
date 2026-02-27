import json
import os
from datetime import datetime, timezone

class JournalEngine:

    def __init__(self):
        self.folder = "logs"
        if not os.path.exists(self.folder):
            os.makedirs(self.folder)

    def save_trade(self, trade_data):

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_path = os.path.join(self.folder, f"journal_{date_str}.json")

        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                data = json.load(f)
        else:
            data = []

        data.append(trade_data)

        with open(file_path, "w") as f:
            json.dump(data, f, indent=4)
