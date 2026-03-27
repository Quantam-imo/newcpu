def run_pipeline(fetch_all_data, process_all):
    data = fetch_all_data()
    result = process_all(data)
    return result