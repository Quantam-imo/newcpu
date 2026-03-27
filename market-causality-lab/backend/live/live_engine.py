import time


def live_loop(fetch_data_func, process_func):
    while True:
        df = fetch_data_func()
        result = process_func(df)

        print("\nLIVE SIGNAL:", result)

        time.sleep(60)  # every 1 min