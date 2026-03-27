import requests

def get_signal():
    res = requests.get("http://localhost:3000/btc/signal")
    return res.json()
