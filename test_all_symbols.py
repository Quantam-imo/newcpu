import databento
client = databento.Historical('db-9YYc6umB6fA7Yv9rF5YjVhFT6Sips')
symbols = ['GC.c.1','GC.FUT','GCJ6','GCM6','GCZ6',
           'NQ.c.1','NQ.FUT','NQH6','NQM6','NQZ6',
           '6E.c.1','6E.FUT','6EH6','6EM6','6EZ6',
           'BTC.c.1','BTC.FUT','BTCH6','BTCM6','BTCZ6',
           'YM.c.1','YM.FUT','YMH6','YMM6','YMZ6']
for sym in symbols:
    try:
        data = client.timeseries.get_range(dataset='GLBX.MDP3', schema='ohlcv-1m', symbols=[sym], start='2026-03-18T00:00:00+00:00', end='2026-03-18T00:10:00+00:00')
        print(sym, list(data)[:1])
    except Exception as e:
        print(sym, 'ERROR:', e)
