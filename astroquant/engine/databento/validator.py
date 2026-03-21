def validate_data(data):
    """
    Ensure data is usable.
    """
    if data is None:
        return False, "No data returned"
    if len(data) == 0:
        return False, "Empty dataset"
    return True, "OK"
