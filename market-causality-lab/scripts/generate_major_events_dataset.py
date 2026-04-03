#!/usr/bin/env python3
"""Generate a curated major global events dataset (2000-2026) with UTC timestamps.

Output schema is compatible with load_news_data:
- time,event,impact,category,source,region,notes
"""

from __future__ import annotations

import csv
from pathlib import Path

OUT_PATH = Path("market-causality-lab/data/global_events_2000_2026_major.csv")

# Curated high-signal events relevant to macro regime shifts and risk sentiment.
EVENTS = [
    ("2000-03-10 14:30:00+00:00", "Dot-com peak (NASDAQ Composite)", "high", "markets", "curated_public_record", "US", "Regime shift to risk-off"),
    ("2001-09-11 12:46:00+00:00", "September 11 attacks", "high", "geopolitics", "curated_public_record", "US", "Global risk shock"),
    ("2001-09-17 13:15:00+00:00", "Federal Reserve emergency rate cut", "high", "rates", "curated_public_record", "US", "Post-attack policy response"),
    ("2003-03-20 02:34:00+00:00", "Iraq War invasion begins", "high", "geopolitics", "curated_public_record", "Middle East", "Major geopolitical risk event"),
    ("2004-11-02 17:00:00+00:00", "US Presidential Election 2004", "medium", "politics", "curated_public_record", "US", "Election risk"),
    ("2005-08-29 11:10:00+00:00", "Hurricane Katrina landfall", "high", "climate", "curated_public_record", "US", "Energy and logistics shock"),
    ("2007-08-09 08:00:00+00:00", "BNP Paribas freezes funds (credit crisis signal)", "high", "credit", "curated_public_record", "EU", "Pre-GFC stress marker"),
    ("2008-09-15 01:45:00+00:00", "Lehman Brothers bankruptcy", "high", "credit", "curated_public_record", "US", "Global financial crisis acceleration"),
    ("2008-10-03 18:30:00+00:00", "TARP signed into law", "high", "policy", "curated_public_record", "US", "Crisis stabilization measure"),
    ("2009-03-09 14:30:00+00:00", "Post-crisis equity trough (S&P 500)", "high", "markets", "curated_public_record", "US", "Risk regime reversal"),
    ("2010-05-06 18:45:00+00:00", "US Flash Crash", "high", "markets", "curated_public_record", "US", "Microstructure stress"),
    ("2010-11-03 18:15:00+00:00", "Federal Reserve announces QE2", "high", "rates", "curated_public_record", "US", "Liquidity regime shift"),
    ("2011-03-11 05:46:00+00:00", "Tohoku earthquake and tsunami", "high", "geopolitics", "curated_public_record", "Japan", "Global supply-chain disruption"),
    ("2011-08-05 22:15:00+00:00", "S&P downgrades US sovereign credit", "high", "credit", "curated_public_record", "US", "Sovereign risk event"),
    ("2012-07-26 09:26:00+00:00", "ECB 'whatever it takes' speech", "high", "rates", "curated_public_record", "EU", "Eurozone tail-risk compression"),
    ("2013-06-19 18:00:00+00:00", "Fed taper signal (taper tantrum)", "high", "rates", "curated_public_record", "US", "Rates volatility spike"),
    ("2014-06-20 00:00:00+00:00", "ISIS territorial escalation", "high", "geopolitics", "curated_public_record", "Middle East", "Energy/geopolitical risk"),
    ("2014-10-31 18:00:00+00:00", "Federal Reserve ends QE3", "high", "rates", "curated_public_record", "US", "Liquidity regime transition"),
    ("2015-08-11 01:00:00+00:00", "PBoC yuan devaluation", "high", "fx", "curated_public_record", "China", "Global risk-off shock"),
    ("2015-12-16 19:00:00+00:00", "Federal Reserve first hike of cycle", "high", "rates", "curated_public_record", "US", "Policy normalization"),
    ("2016-06-24 03:00:00+00:00", "Brexit referendum result", "high", "politics", "curated_public_record", "UK", "Large FX and risk repricing"),
    ("2016-11-09 07:00:00+00:00", "US Presidential Election result", "high", "politics", "curated_public_record", "US", "Cross-asset regime rotation"),
    ("2017-12-14 19:00:00+00:00", "Fed balance-sheet runoff era", "medium", "rates", "curated_public_record", "US", "Liquidity tightening phase"),
    ("2018-02-05 21:00:00+00:00", "Volmageddon (VIX spike)", "high", "markets", "curated_public_record", "US", "Volatility regime shock"),
    ("2018-12-19 19:00:00+00:00", "Fed hike amid growth slowdown", "medium", "rates", "curated_public_record", "US", "Late-cycle tightening stress"),
    ("2019-08-14 14:00:00+00:00", "US yield curve inversion", "high", "rates", "curated_public_record", "US", "Recession signal event"),
    ("2020-01-30 21:30:00+00:00", "WHO declares COVID-19 Public Health Emergency", "high", "health", "curated_public_record", "Global", "Pandemic escalation"),
    ("2020-03-11 20:00:00+00:00", "WHO declares COVID-19 pandemic", "high", "health", "curated_public_record", "Global", "Global risk-off catalyst"),
    ("2020-03-15 21:00:00+00:00", "Fed emergency cut to near zero + QE restart", "high", "rates", "curated_public_record", "US", "Crisis policy pivot"),
    ("2020-04-20 18:09:00+00:00", "WTI front-month settles below zero", "high", "commodities", "curated_public_record", "US", "Energy market dislocation"),
    ("2020-11-09 11:45:00+00:00", "First major COVID vaccine efficacy result", "high", "health", "curated_public_record", "Global", "Reopening regime shift"),
    ("2021-01-06 19:00:00+00:00", "US Capitol attack", "high", "politics", "curated_public_record", "US", "Political risk spike"),
    ("2021-03-23 12:00:00+00:00", "Suez Canal blockage", "medium", "logistics", "curated_public_record", "Global", "Trade and supply-chain disruption"),
    ("2021-11-03 18:00:00+00:00", "Fed taper announcement", "high", "rates", "curated_public_record", "US", "Shift away from ultra-loose policy"),
    ("2022-02-24 04:00:00+00:00", "Russia invades Ukraine", "high", "geopolitics", "curated_public_record", "Europe", "Energy, metals, and risk shock"),
    ("2022-03-16 18:00:00+00:00", "Federal Reserve starts 2022 tightening cycle", "high", "rates", "curated_public_record", "US", "Inflation fight regime"),
    ("2022-09-26 09:00:00+00:00", "UK gilt market stress and LDI crisis", "high", "credit", "curated_public_record", "UK", "Rates/liquidity shock"),
    ("2022-11-30 13:00:00+00:00", "OpenAI ChatGPT release", "medium", "technology", "curated_public_record", "Global", "AI thematic regime event"),
    ("2023-03-10 16:00:00+00:00", "Silicon Valley Bank failure", "high", "credit", "curated_public_record", "US", "Banking stress event"),
    ("2023-03-19 22:00:00+00:00", "UBS acquires Credit Suisse", "high", "credit", "curated_public_record", "EU", "Systemic bank-risk containment"),
    ("2023-10-07 06:30:00+00:00", "Israel-Hamas war outbreak", "high", "geopolitics", "curated_public_record", "Middle East", "Geopolitical risk repricing"),
    ("2024-01-11 21:00:00+00:00", "Spot Bitcoin ETF approvals in US", "medium", "markets", "curated_public_record", "US", "Crypto-market structure shift"),
    ("2024-04-13 23:00:00+00:00", "Iran-Israel direct missile/drone exchange", "high", "geopolitics", "curated_public_record", "Middle East", "Acute geopolitical risk"),
    ("2024-11-05 23:00:00+00:00", "US Presidential Election 2024", "high", "politics", "curated_public_record", "US", "Election regime uncertainty"),
    ("2025-01-20 17:00:00+00:00", "US Presidential inauguration 2025", "medium", "politics", "curated_public_record", "US", "Policy transition"),
    ("2025-06-30 12:00:00+00:00", "Mid-year global policy and conflict checkpoint", "medium", "macro", "curated_public_record", "Global", "Placeholder for ongoing 2025 cycle"),
    ("2026-01-01 00:00:00+00:00", "2026 macro cycle opening marker", "medium", "macro", "curated_public_record", "Global", "Anchor timestamp for 2026 simulations"),
]


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "event", "impact", "category", "source", "region", "notes"])
        for row in EVENTS:
            ts = row[0]
            if "T" not in ts and " " in ts:
                ts = ts.replace(" ", "T", 1)
            w.writerow([ts, *row[1:]])

    print(f"Wrote {len(EVENTS)} rows to {OUT_PATH}")
    print(f"Coverage: {EVENTS[0][0]} -> {EVENTS[-1][0]}")


if __name__ == "__main__":
    main()
