import time
from astroquant.ai.feedback_loop import adjust_strategy

def run_learning_loop():
    while True:
        result = adjust_strategy()
        print("AI Updated:", result)
        time.sleep(3600)  # every 1 hour
