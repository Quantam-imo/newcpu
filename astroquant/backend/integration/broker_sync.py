def fetch_equity_from_browser(page):
    try:
        equity_text = page.locator("[data-testid='account-equity']").inner_text()
        return float(equity_text.replace(",", "").strip())
    except Exception:
        return None
