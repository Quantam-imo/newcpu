import os
import databento as db

api_key = os.environ.get('DATABENTO_API_KEY')
print(f'API key present: {bool(api_key)}')
try:
    client = db.Historical(api_key)
    datasets = client.list_datasets()
    print('Datasets:', datasets)
except Exception as e:
    print('Databento auth error:', e)
