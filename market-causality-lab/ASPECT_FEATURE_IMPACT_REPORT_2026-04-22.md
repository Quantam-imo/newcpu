# Aspect Feature Impact Report (2026-04-22)

## Scope
Coefficient-based feature impact review for retrained logistic models:
- 1h buy: memory-20260422T031658Z
- 4h buy: memory-20260422T021608Z

Method:
- Use absolute value of logistic regression weights (|w|) on standardized features.
- Higher |w| implies stronger influence in the linear decision function.
- Rank is across all 110 `v4_layered_execution` features.

## 1h Buy (memory-20260422T031658Z)
Validation:
- Brier: 0.128237
- Accuracy: 0.849866

Top 10 overall features (by |w|):
1. base_volatility (0.192159)
2. participation_score (0.141537)
3. participation_volume_spike (0.135643)
4. state_price (0.113857)
5. news_square_count (0.090540)
6. compression_bars_in_compression (0.084390)
7. compression_score (0.077857)
8. news_nakshatra_event_count (0.073725)
9. participation_newyork_open (0.073721)
10. news_event_count (0.058773)

Named aspect feature impact:
- news_square_count: w=+0.090540, rank #5
- news_nakshatra_event_count: w=-0.073725, rank #8
- news_opposition_count: w=-0.048488, rank #17
- news_trine_count: w=-0.038390, rank #30
- news_gann_event_count: w=+0.031561, rank #37
- news_ingress_event_count: w=-0.027625, rank #40
- news_conjunction_count: w=-0.013464, rank #64
- news_aspect_event_count: w=+0.010578, rank #70
- news_sextile_count: w=+0.001806, rank #90
- news_eclipse_event_count: w=+0.000000, rank #94

Interpretation:
- On 1h buy, square and nakshatra counts are high-signal features (top 10 overall).
- Opposition is also meaningful (top 20).
- Eclipse had no learned effect in this run.

## 4h Buy (memory-20260422T021608Z)
Validation:
- Brier: 0.162066
- Accuracy: 0.829268

Top 10 overall features (by |w|):
1. location_session_high_near (0.298078)
2. participation_london_open (0.297218)
3. location_bullish_fvg_near (0.274383)
4. cycle_days_to_next_node (0.272029)
5. state_price (0.241998)
6. cycle_planetary_active (0.234444)
7. structure_choch_down (0.211616)
8. trigger_mss_bearish (0.211616)
9. news_ingress_event_count (0.195821)
10. time_moon_full_active (0.177649)

Named aspect feature impact:
- news_ingress_event_count: w=-0.195821, rank #9
- news_nakshatra_event_count: w=+0.159026, rank #13
- news_trine_count: w=+0.144069, rank #15
- news_sextile_count: w=+0.087261, rank #33
- news_aspect_event_count: w=+0.086786, rank #34
- news_opposition_count: w=-0.066977, rank #44
- news_gann_event_count: w=-0.032099, rank #71
- news_conjunction_count: w=-0.013604, rank #82
- news_square_count: w=+0.007558, rank #85
- news_eclipse_event_count: w=+0.000000, rank #92

Interpretation:
- On 4h buy, ingress is a top-10 driver, with nakshatra and trine also strong (top 15).
- Aspect features matter differently by timeframe: square dominates on 1h, ingress/trine/nakshatra dominate on 4h.
- Eclipse again shows no learned effect.

## Cross-Timeframe Takeaways
- Most consistently useful new concept families: nakshatra, ingress, and at least one geometric aspect (square on 1h, trine on 4h).
- The model is learning directional effects (positive/negative sign) that differ by timeframe.
- Zero-weight eclipse suggests low information density under current horizon/labels.

## Notes
- Weight magnitude is a linear-model proxy, not causal inference.
- Feature signs indicate push direction in log-odds, conditional on all other features.
