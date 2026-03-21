from datetime import timedelta, datetime, timezone

# Global offset
DATA_TIME_OFFSET = None

def update_data_offset(latest_data_time, system_time):
    global DATA_TIME_OFFSET
    DATA_TIME_OFFSET = system_time - latest_data_time
    print(f"[SYNC] Offset: {DATA_TIME_OFFSET}")

def get_synced_now():
    if DATA_TIME_OFFSET is None:
        return datetime.now(timezone.utc)
    return datetime.now(timezone.utc) - DATA_TIME_OFFSET

def get_synced_window(minutes=30):
    end = get_synced_now()
    start = end - timedelta(minutes=minutes)
    return start, end
