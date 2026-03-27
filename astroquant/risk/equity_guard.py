def allow_trade():
    # Example logic
    daily_loss = get_daily_loss()
    if daily_loss > 100:
        return False
    return True
