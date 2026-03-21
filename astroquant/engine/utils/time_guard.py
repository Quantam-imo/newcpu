from datetime import datetime, timedelta, timezone

# Adjustable buffer (IMPORTANT)
BUFFER_MINUTES = 12

def get_safe_utc_now():
    """
    Returns safe UTC time to avoid future data requests.
    """
    return datetime.now(timezone.utc) - timedelta(minutes=BUFFER_MINUTES)

def clamp_start_time(start_time):
    """
    Ensures start_time is not in the future.
    """
    safe_now = get_safe_utc_now()
    if start_time >= safe_now:
        return safe_now - timedelta(minutes=5)
    return start_time

def get_query_window(minutes=30):
    """
    Returns a safe start and end time window.
    """
    end = get_safe_utc_now()
    start = end - timedelta(minutes=minutes)
    return start, end
