import time
from execution.clawbot import ClawBot
from api.signal_provider import get_signal  # your API

bot = ClawBot()

while True:
    try:
        signal_data = get_signal()
        bot.process_signal(signal_data)
        time.sleep(5)
    except Exception as e:
        print("Loop error:", e)
        time.sleep(5)
