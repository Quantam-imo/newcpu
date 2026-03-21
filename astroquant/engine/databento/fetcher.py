import databento as db
from astroquant.engine.utils.time_guard import get_query_window

def fetch_live_data(symbol="GLBX.MDP3", minutes=30):
    client = db.Historical()
    try:
        start, end = get_query_window(minutes)
        print(f"[TIME CHECK] Safe UTC Now: {end}")
        print(f"[INFO] Fetching from {start} to {end}")
        data = client.timeseries.get_range(
            dataset=symbol,
            start=start,
            end=end,
            schema="ohlcv-1m"
        )
        return data
    except Exception as e:
        print(f"[ERROR] Initial fetch failed: {e}")
        # Retry with fallback window
        try:
            print("[RETRY] Using fallback window...")
            start, end = get_query_window(minutes + 10)
            data = client.timeseries.get_range(
                dataset=symbol,
                start=start,
                end=end,
                schema="ohlcv-1m"
            )
            return data
        except Exception as retry_error:
            print(f"[FATAL] Retry failed: {retry_error}")
            return None
