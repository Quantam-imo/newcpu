import databento as db

def print_record(record):
    print("RECORD:", record)
    if hasattr(record, 'err'):
        print("ERROR:", record.err)

def print_error(exception):
    print("EXCEPTION:", exception)

client = db.Live(key="db-9YYc6umB6fA7Yv9rF5YjVhFT6Sips")

client.subscribe(
    dataset="GLBX.MDP3",
    schema="trades",
    symbols="ES.FUT",
    stype_in="parent",
    start="2023-04-17T09:00:00",
)

client.add_callback(print_record, exception_callback=print_error)

print("Starting live session. Waiting for data or errors...")
client.start()
client.block_for_close(timeout=10)  # Wait up to 10 seconds for data
print("Session ended or timed out.")
