def calculate_lot(balance, risk_percent, sl_points):
    risk_amount = balance * (risk_percent / 100)

    lot = risk_amount / sl_points

    return round(lot, 2)
