import databento as db
API_KEY = "REDACTED"

client = db.Historical(API_KEY)
symbols = ['GCZ6','GCM6','GCF6','GCG6','GCH6','GCJ6','GCK6','GCL6','GCN6','GCQ6','GCU6','GCX6']
for sym in symbols:
    try:
        data = client.timeseries.get_range(dataset='GLBX.MDP3', schema='ohlcv-1m', symbols=[sym], start='2026-03-18T00:00:00+00:00', end='2026-03-18T00:10:00+00:00')
        print(sym, list(data)[:1])
    except Exception as e:
        print(sym, 'ERROR:', e)
