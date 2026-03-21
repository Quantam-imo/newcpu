from astroquant.engine.databento.fetcher import fetch_live_data
from astroquant.engine.databento.validator import validate_data

def get_databento_feed():
    data = fetch_live_data()
    is_valid, msg = validate_data(data)
    return {
        "status": "ok" if is_valid else "error",
        "message": msg,
        "data": data if is_valid else []
    }
