import os
import databento as db

api_key = os.environ.get('DATABENTO_API_KEY')
print(f'API key present: {bool(api_key)}')
try:
    client = db.Historical(api_key)
    print('Historical timeseries object:', client.timeseries)
except Exception as e:
    print('Databento auth error:', e)
