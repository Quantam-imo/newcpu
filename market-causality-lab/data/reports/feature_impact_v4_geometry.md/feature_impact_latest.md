# Feature Impact Report (2026-04-22)

Auto-generated from current latest first-touch model pointers.
Weight impact uses absolute logistic coefficients on standardized features.

## Snapshot

| Scope Pointer | Version | TF | Setup | Label | Model | Brier | Accuracy |
|---|---|---|---|---|---|---:|---:|
| latest_15m__all_bars__first_touch_buy.json | memory-20260422T124515Z | 15m | all_bars | first_touch_buy | logistic_gd | 0.034333 | 0.962540 |
| latest_1d__all_bars__first_touch_buy.json | memory-20260422T094350Z | 1d | all_bars | first_touch_buy | prior | 0.249063 | 0.530612 |
| latest_1d__all_bars__first_touch_sell.json | memory-20260422T030332Z | 1d | all_bars | first_touch_sell | prior | 0.230793 | 0.638591 |
| latest_1h__all_bars__first_touch_buy.json | memory-20260422T093625Z | 1h | all_bars | first_touch_buy | prior | 0.210095 | 0.699764 |
| latest_1h__buy_trigger_candidate__first_touch_buy.json | memory-20260422T101340Z | 1h | buy_trigger_candidate | first_touch_buy | logistic_gd | 0.182292 | 0.746667 |
| latest_1h__sell_trigger_candidate__first_touch_sell.json | memory-20260422T102043Z | 1h | sell_trigger_candidate | first_touch_sell | prior | 0.137482 | 0.835443 |
| latest_1month__all_bars__first_touch_buy.json | memory-20260422T100212Z | 1month | all_bars | first_touch_buy | momentum_rule | 0.231597 | 0.739130 |
| latest_1month__all_bars__first_touch_sell.json | memory-20260422T090153Z | 1month | all_bars | first_touch_sell | prior | 0.231388 | 0.695652 |
| latest_1w__all_bars__first_touch_buy.json | memory-20260422T100230Z | 1w | all_bars | first_touch_buy | prior | 0.248928 | 0.532751 |
| latest_1w__all_bars__first_touch_sell.json | memory-20260422T030053Z | 1w | all_bars | first_touch_sell | prior | 0.238554 | 0.606987 |
| latest_30m__all_bars__first_touch_buy.json | memory-20260422T154135Z | 30m | all_bars | first_touch_buy | logistic_gd | 0.070476 | 0.918600 |
| latest_4h__all_bars__first_touch_buy.json | memory-20260422T094530Z | 4h | all_bars | first_touch_buy | prior | 0.220229 | 0.672542 |
| latest_4h__buy_trigger_candidate__first_touch_buy.json | memory-20260422T021608Z | 4h | buy_trigger_candidate | first_touch_buy | logistic_gd | 0.162066 | 0.829268 |
| latest_4h__sell_trigger_candidate__first_touch_sell.json | memory-20260422T021700Z | 4h | sell_trigger_candidate | first_touch_sell | prior | 0.211206 | 0.696970 |
| latest_5m__all_bars__first_touch_buy.json | memory-20260422T123611Z | 5m | all_bars | first_touch_buy | prior | 0.010528 | 0.989359 |

## 15m / all_bars / first_touch_buy

- pointer: latest_15m__all_bars__first_touch_buy.json
- version: memory-20260422T124515Z
- model: logistic_gd
- brier: 0.034333
- accuracy: 0.962540
- log_loss: 0.147581

Top 10 features by |weight|:

| Rank | Feature | Weight | |Weight| |
|---:|---|---:|---:|
| 1 | base_volatility | 0.067155 | 0.067155 |
| 2 | physics_force | 0.057287 | 0.057287 |
| 3 | compression_energy_stored | -0.037015 | 0.037015 |
| 4 | participation_newyork_open | 0.024901 | 0.024901 |
| 5 | participation_score | 0.016135 | 0.016135 |
| 6 | gann_tangent_angle_deg | 0.014682 | 0.014682 |
| 7 | gann_tangent_expansion_strength | 0.014682 | 0.014682 |
| 8 | state_price | -0.014356 | 0.014356 |
| 9 | structure_trend_strength | 0.008296 | 0.008296 |
| 10 | compression_score | -0.007815 | 0.007815 |

Named aspect features:

| Feature | Rank | Weight | |Weight| |
|---|---:|---:|---:|
| news_aspect_event_count | 43 | 0.003139 | 0.003139 |
| news_conjunction_count | 18 | 0.005182 | 0.005182 |
| news_square_count | 15 | 0.005541 | 0.005541 |
| news_opposition_count | 21 | -0.004842 | 0.004842 |
| news_trine_count | 64 | -0.001542 | 0.001542 |
| news_sextile_count | 72 | 0.001226 | 0.001226 |
| news_ingress_event_count | 68 | -0.001302 | 0.001302 |
| news_nakshatra_event_count | 74 | -0.001213 | 0.001213 |
| news_gann_event_count | 105 | -0.000382 | 0.000382 |
| news_eclipse_event_count | 111 | -0.000013 | 0.000013 |

## 1d / all_bars / first_touch_buy

- pointer: latest_1d__all_bars__first_touch_buy.json
- version: memory-20260422T094350Z
- model: prior
- brier: 0.249063
- accuracy: 0.530612
- log_loss: 0.691272
- impact extraction: skipped (best_model_not_logistic)

## 1d / all_bars / first_touch_sell

- pointer: latest_1d__all_bars__first_touch_sell.json
- version: memory-20260422T030332Z
- model: prior
- brier: 0.230793
- accuracy: 0.638591
- log_loss: 0.654225
- impact extraction: skipped (best_model_not_logistic)

## 1h / all_bars / first_touch_buy

- pointer: latest_1h__all_bars__first_touch_buy.json
- version: memory-20260422T093625Z
- model: prior
- brier: 0.210095
- accuracy: 0.699764
- log_loss: 0.611065
- impact extraction: skipped (best_model_not_logistic)

## 1h / buy_trigger_candidate / first_touch_buy

- pointer: latest_1h__buy_trigger_candidate__first_touch_buy.json
- version: memory-20260422T101340Z
- model: logistic_gd
- brier: 0.182292
- accuracy: 0.746667
- log_loss: 0.552094

Top 10 features by |weight|:

| Rank | Feature | Weight | |Weight| |
|---:|---|---:|---:|
| 1 | participation_score | 0.176105 | 0.176105 |
| 2 | trigger_sweep_buy_side | -0.167043 | 0.167043 |
| 3 | time_nakshatra_transition_active | -0.162043 | 0.162043 |
| 4 | time_moon_full_active | 0.123396 | 0.123396 |
| 5 | participation_volume_spike | 0.122490 | 0.122490 |
| 6 | time_moon_phase_active | 0.115939 | 0.115939 |
| 7 | location_bearish_order_block_near | -0.112962 | 0.112962 |
| 8 | time_gann_synodic_active | 0.109364 | 0.109364 |
| 9 | participation_strong | 0.108631 | 0.108631 |
| 10 | cycle_moon_phase_position | 0.107157 | 0.107157 |

Named aspect features:

| Feature | Rank | Weight | |Weight| |
|---|---:|---:|---:|
| news_aspect_event_count | 65 | 0.037080 | 0.037080 |
| news_conjunction_count | 88 | -0.013738 | 0.013738 |
| news_square_count | 12 | 0.105465 | 0.105465 |
| news_opposition_count | 20 | -0.090798 | 0.090798 |
| news_trine_count | 48 | 0.047311 | 0.047311 |
| news_sextile_count | 99 | -0.000063 | 0.000063 |
| news_ingress_event_count | 43 | -0.049453 | 0.049453 |
| news_nakshatra_event_count | 11 | 0.106594 | 0.106594 |
| news_gann_event_count | 40 | 0.052782 | 0.052782 |
| news_eclipse_event_count | 100 | 0.000000 | 0.000000 |

## 1h / sell_trigger_candidate / first_touch_sell

- pointer: latest_1h__sell_trigger_candidate__first_touch_sell.json
- version: memory-20260422T102043Z
- model: prior
- brier: 0.137482
- accuracy: 0.835443
- log_loss: 0.447164
- impact extraction: skipped (best_model_not_logistic)

## 1month / all_bars / first_touch_buy

- pointer: latest_1month__all_bars__first_touch_buy.json
- version: memory-20260422T100212Z
- model: momentum_rule
- brier: 0.231597
- accuracy: 0.739130
- log_loss: 0.741992
- impact extraction: skipped (best_model_not_logistic)

## 1month / all_bars / first_touch_sell

- pointer: latest_1month__all_bars__first_touch_sell.json
- version: memory-20260422T090153Z
- model: prior
- brier: 0.231388
- accuracy: 0.695652
- log_loss: 0.655783
- impact extraction: skipped (best_model_not_logistic)

## 1w / all_bars / first_touch_buy

- pointer: latest_1w__all_bars__first_touch_buy.json
- version: memory-20260422T100230Z
- model: prior
- brier: 0.248928
- accuracy: 0.532751
- log_loss: 0.691002
- impact extraction: skipped (best_model_not_logistic)

## 1w / all_bars / first_touch_sell

- pointer: latest_1w__all_bars__first_touch_sell.json
- version: memory-20260422T030053Z
- model: prior
- brier: 0.238554
- accuracy: 0.606987
- log_loss: 0.670077
- impact extraction: skipped (best_model_not_logistic)

## 30m / all_bars / first_touch_buy

- pointer: latest_30m__all_bars__first_touch_buy.json
- version: memory-20260422T154135Z
- model: logistic_gd
- brier: 0.070476
- accuracy: 0.918600
- log_loss: 0.260092

Top 10 features by |weight|:

| Rank | Feature | Weight | |Weight| |
|---:|---|---:|---:|
| 1 | base_volatility | 0.082513 | 0.082513 |
| 2 | participation_volume_spike | 0.075639 | 0.075639 |
| 3 | physics_force | 0.061642 | 0.061642 |
| 4 | participation_score | 0.058541 | 0.058541 |
| 5 | participation_newyork_open | 0.051075 | 0.051075 |
| 6 | compression_energy_stored | -0.040866 | 0.040866 |
| 7 | gann_tangent_angle_deg | 0.028800 | 0.028800 |
| 8 | gann_tangent_expansion_strength | 0.028800 | 0.028800 |
| 9 | participation_london_open | -0.017201 | 0.017201 |
| 10 | news_square_count | 0.015309 | 0.015309 |

Named aspect features:

| Feature | Rank | Weight | |Weight| |
|---|---:|---:|---:|
| news_aspect_event_count | 92 | -0.000862 | 0.000862 |
| news_conjunction_count | 89 | 0.001167 | 0.001167 |
| news_square_count | 10 | 0.015309 | 0.015309 |
| news_opposition_count | 15 | -0.009990 | 0.009990 |
| news_trine_count | 19 | -0.008822 | 0.008822 |
| news_sextile_count | 42 | -0.004190 | 0.004190 |
| news_ingress_event_count | 32 | -0.005470 | 0.005470 |
| news_nakshatra_event_count | 101 | -0.000343 | 0.000343 |
| news_gann_event_count | 84 | -0.001333 | 0.001333 |
| news_eclipse_event_count | 27 | -0.006396 | 0.006396 |

## 4h / all_bars / first_touch_buy

- pointer: latest_4h__all_bars__first_touch_buy.json
- version: memory-20260422T094530Z
- model: prior
- brier: 0.220229
- accuracy: 0.672542
- log_loss: 0.632364
- impact extraction: skipped (best_model_not_logistic)

## 4h / buy_trigger_candidate / first_touch_buy

- pointer: latest_4h__buy_trigger_candidate__first_touch_buy.json
- version: memory-20260422T021608Z
- model: logistic_gd
- brier: 0.162066
- accuracy: 0.829268
- log_loss: 0.503630
- impact extraction: skipped (weight_vector_missing_or_mismatch)

## 4h / sell_trigger_candidate / first_touch_sell

- pointer: latest_4h__sell_trigger_candidate__first_touch_sell.json
- version: memory-20260422T021700Z
- model: prior
- brier: 0.211206
- accuracy: 0.696970
- log_loss: 0.613418
- impact extraction: skipped (best_model_not_logistic)

## 5m / all_bars / first_touch_buy

- pointer: latest_5m__all_bars__first_touch_buy.json
- version: memory-20260422T123611Z
- model: prior
- brier: 0.010528
- accuracy: 0.989359
- log_loss: 0.058935
- impact extraction: skipped (best_model_not_logistic)

