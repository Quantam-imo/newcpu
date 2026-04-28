# Frontend Missing Aspects Report
**Date:** 2026-04-24 | **Status:** Comprehensive Audit Complete

---

## Executive Summary

Both MCL and AstroQuant frontends have extensive concept visualizations **(Gann, Astro, Lunar, ICT, Vibration)**, but are **missing critical Elliott wave displays and AI feature importance rankings** that correspond to the trained v4/v5 model stack.

### Training vs Frontend Mismatch:
- **v5 Elliott Features:** 15 Elliott wave features trained and operational (1d, 4h complete; 1h, 30m, 15m, 5m in repair)
- **v4 Features:** 120 features (Gann + Astro + ICT + time-engine + location + trigger + participation layers)
- **Frontend Displays:** Missing Elliott wave visualization, NO feature importance weights visible, NO model drift UI

---

## Market Causality Lab (MCL) Dashboard

### ✅ Currently Displayed

#### Charting & Overlays
- **Chart Core:** Candlestick data with volume coloring ✓
- **Gann Angles:** 1×1, 2×1, 1×2 lines from swing lows ✓
- **Cycle Markers:** 30/45/90/180/360-bar intervals ✓
- **Pattern Overlays:** Swing highs/lows, BOS/CHOCH breaks ✓
- **Lunar Events:** New Moon, Full Moon markers ✓
- **Gann 360° Wheel:** Live price degree, SQ9 levels ✓
- **Lesson Annotations:** L1-Lunar, L2-Vibration, L3-ASC+SQ9 overlays ✓

#### Analysis Panels
- **52-Question Gann Scoring:** Comprehensive verdict system ✓
- **Gann 360° Calendar:** Monthly angle dates with market state (RISE/BALANCE/RELEASE) ✓
- **Astrology Module:** Moon phases, planet positions, aspects, Gann-planet alignments ✓
- **Lunar Expansion Engine:** Cycle day, phase badge, expansion score, ICT filter ✓
- **Law of Vibration:** Node signal, 3-6-9 harmonics, price vibration, ascendant ✓
- **ASC + Square of 9:** Timing dial, time nodes table, ICT filter, signal rules ✓
- **Trade History Matrix:** Last 50 outcomes, accuracy tracking ✓
- **Learning Engine Weights:** Signal weight calibration, batch replay ✓

#### Mathematical Validation
- Mathematical Validation (MATH_01..MATH_15) questions ✓
- Post-Trade Review modal ✓

---

### ❌ **MISSING ASPECTS** (Critical Gaps)

#### 1. **Elliott Wave Visualization Layer**
- **What's Missing:**
  - No Elliott impulse/corrective phase display on chart
  - No wave count overlay (1-5 for impulse, A-C for correction)
  - No wave confidence/strength indicator
  - No Elliott cycle alignment scoring visible
  - No multi-timeframe Elliott validation display
  
- **Should Display:**
  - Current Elliott phase badge (Impulse/Corrective/Transitional)
  - Wave position (e.g., "Wave 3 of Impulse")
  - Confidence score (v5 feature: `impulse_confidence`, `corrective_confidence`)
  - Direction and progress metrics
  - Alignment with Gann angles and astro events
  
- **Data Source:** Already computed in scanner.py `_extract_elliott_wave_context()` (15 features)
- **UI Placement:** Add to chart as overlay toggle + summary card

#### 2. **Feature Importance Ranking & Weights**
- **What's Missing:**
  - No display of which features are driving buy/sell decisions
  - No feature weight visualization by timeframe
  - No feature impact bar chart or ranked list
  - No model version indicator (v3 vs v4 vs v5)
  - No drift indicator comparing expected vs actual feature weights
  
- **Should Display:**
  - Top 10 features ranked by importance/weight
  - By timeframe (1h, 4h, 1d, etc.)
  - By concept (Gann, Astro, ICT, Elliott, Time-Engine)
  - Weight change from baseline (green/red indicator)
  - Live feature contribution % to current signal
  
- **Data Source:** Exists in ASPECT_FEATURE_IMPACT_REPORT_2026-04-22.md
  - Example: "1h buy: square (rank #5), nakshatra (rank #8), opposition (rank #17)"
  - Can be queried from `/market_causality/feature_impact_by_timeframe` endpoint (needs to be created)
  
- **UI Placement:** New expandable section or mini-panel below AI Model Absorption

#### 3. **Model Drift Detection UI**
- **What's Missing:**
  - No alert when model weights diverge from expected patterns
  - No calibration status indicator
  - No feature staleness warning
  - No version mismatch indicator (e.g., using v3 when v5 available)
  
- **Should Display:**
  - "Model Status" badge: CALIBRATED / DRIFTED / RETRAINING
  - Feature weight divergence % from baseline
  - Last retrain timestamp
  - Active model version (v3/v4/v5)
  - Warning banner if pointer is missing or in repair
  
- **Data Source:** Train logs, pointer registry
- **UI Placement:** Add to header or AI Model Absorption panel

#### 4. **Multi-Timeframe Concept Comparison**
- **What's Missing:**
  - No side-by-side Elliott phase comparison across timeframes
  - No timeframe alignment checker (e.g., all TFs in same impulse phase?)
  - No concept voting display (how many TFs support the signal?)
  - No cascading validation flow (1m→5m→15m→1h→4h→1d agreement)
  
- **Should Display:**
  - Timeframe matrix: Elliott Phase | Gann Angle | Astro Event | ICT Status
  - ✓/✗ indicators showing alignment across TFs
  - Confluence score per timeframe
  - Overall multi-TF signal strength
  
- **UI Placement:** New "Timeframe Alignment Matrix" section

#### 5. **v4 vs v5 Layer Toggle**
- **What's Missing:**
  - No UI control to switch between v4_layered_execution and v5_elliott_unified displays
  - No feature layer breakdown (Gann layer | Astro layer | ICT layer | Elliott layer)
  - No A/B comparison view
  
- **Should Display:**
  - Toggle: "View as v4 (Gann+Astro+ICT)" or "View as v5 (+ Elliott)"
  - Layer breakdown card showing feature counts per layer
  - Signal difference if v4 vs v5 disagree
  - Which model is currently active
  
- **UI Placement:** Header controls or Settings panel

#### 6. **Chart Annotation Enhancements**
- **What's Missing:**
  - No Elliott wave labels on chart (Wave 1, Wave 2, etc.)
  - No Elliott cycle markers (different colors/styles for impulse vs correction)
  - No feature event markers (e.g., pink diamond when "square" feature triggered)
  - No model prediction path visualization
  
- **Should Display on Chart:**
  - Elliott phase background shading (light green impulse, light red correction)
  - Wave count labels at swing points
  - Feature trigger annotations on high-impact bars
  - 30-bar forward P(t) prediction curve (already exists, enhance styling)
  
- **UI Placement:** Enhance existing chart overlay system

#### 7. **Feature Contribution Timeline**
- **What's Missing:**
  - No historical view of which features drove past wins/losses
  - No "feature score by bar" sparkline showing real-time feature activation
  - No feature event timeline
  
- **Should Display:**
  - Timeline chart: Top 5 features over last 20 bars
  - Color-coded by feature (Gann=orange, Astro=purple, ICT=blue, Elliott=green)
  - Bar-by-bar feature activation heat map
  - Win/loss correlation to top features
  
- **UI Placement:** New "Feature Timeline" chart below AI Model Absorption

#### 8. **Elliott Concept Learning Status**
- **What's Missing:**
  - No indicator showing training completion per Elliott timeframe
  - No status badge for missing pointers (1h sell, 5m sell still training at 36+ min)
  - No ETA for repair training jobs
  
- **Should Display:**
  - "Elliott Training Status": 1d✓ 4h✓ 1h⏳ 30m⏳ 15m⏳ 5m⏳ 1m⏳
  - Missing pointer list with PID/status/elapsed time
  - Repair job progress % if running
  - Alert banner if critical timeframe pointer missing
  
- **UI Placement:** Status section or floating badge

---

## AstroQuant Frontend

### ✅ Currently Displayed

#### Main Panels
- **Chart:** Streaming candles with volume ✓
- **Symbol Selector:** Autocomplete with smart selection ✓
- **Orderflow/Iceberg:** Tape microstructure ✓
- **Delta Panel:** Buy/Sell volume tracking ✓
- **Mentor Drawer:** Context data placeholder ✓
- **Operations Console:** Trading actions, broker bridge ✓
- **System Health:** Status indicators ✓
- **Gann Wheel:** Rotating angle display (referenced in code) ✓
- **Astro Calendar:** Moon/astro event display ✓
- **Journal:** Trade outcome logging ✓

#### Data Streams
- **Live Price/Volume:** Real-time updates ✓
- **Broker Status:** Connection state ✓
- **Feed Status:** Candles verified count ✓

---

### ❌ **MISSING ASPECTS** (Critical Gaps)

#### 1. **Elliott Wave Chart Overlay**
- **What's Missing:**
  - No Elliott impulse/corrective phase background shading
  - No wave count labels (1-5, A-C)
  - No wave confidence score display
  - No Elliott cycle alignment indicator
  - No cross-symbol Elliott comparison (e.g., GC vs XAUUSD Elliott phases)
  
- **Should Display:**
  - Elliott state badge: e.g., "Wave 3 of Impulse | Confidence 78%"
  - Wave label markers on chart at swing points
  - Colored background (green impulse, red correction)
  - Progress bar showing wave formation %
  
- **Data Source:** Market-causality-lab backend → `/elliott_wave` endpoint
- **UI Placement:** Chart header + overlay toggle in chart.js

#### 2. **Feature Importance Drawer Tab**
- **What's Missing:**
  - Mentor drawer only shows placeholder data
  - No feature weight ranking visible
  - No feature importance breakdown by timeframe
  - No model version info (v3/v4/v5)
  - No feature contribution % to current signal
  
- **Should Display in Mentor Drawer:**
  - New tab: "Features" showing ranked list
  - Top 10 features by weight
  - By concept (Gann, Astro, Elliott, ICT, Time-Engine)
  - Current timeframe selector (1m, 5m, 15m, 1h, 4h, 1d)
  - % impact on current buy/sell signal
  - Color-coded by feature type
  
- **Data Source:** MCL backend feature impact endpoint
- **UI Placement:** mentor.js → add new feature importance panel

#### 3. **Model Drift Alert**
- **What's Missing:**
  - No warning when model weights diverge from baseline
  - No calibration status badge
  - No version mismatch indicator
  - No stale model warning
  
- **Should Display:**
  - Status badge in header: "Model: v5_elliott_unified ✓ CALIBRATED"
  - Or alert if drifted: "⚠️ Model Drifted — Feature weights shifted 15% from baseline"
  - Last trained timestamp
  - Next scheduled retrain time
  
- **Data Source:** Model registry, training logs
- **UI Placement:** System health panel or header badge

#### 4. **Elliott Phase Multi-Timeframe Matrix**
- **What's Missing:**
  - No timeframe alignment checker UI
  - No "how many TFs agree?" display
  - No cascading validation flow (1m→5m→15m→1h→4h→1d)
  - No confluence score per timeframe
  
- **Should Display:**
  - Matrix or sidebar: TF | Elliott Phase | Gann Angle | ICT Status | ✓/✗
  - Green checkmarks where TFs align
  - Red X where divergent
  - Overall confluence % (e.g., "5 of 6 TFs bullish impulse")
  
- **UI Placement:** New collapsible timeframe alignment drawer

#### 5. **Feature Timeline Sparkline**
- **What's Missing:**
  - No bar-by-bar feature activation history
  - No "which features fired on winning trades?" display
  - No feature event timeline visualization
  
- **Should Display:**
  - Mini chart: Last 20 bars with top 3 features highlighted
  - Color-coded bars by dominant feature
  - Win/loss outcome color on bars
  - Hover to see feature name + contribution %
  
- **UI Placement:** New compact panel in operations drawer

#### 6. **Model Version Selector & A/B Toggle**
- **What's Missing:**
  - No UI to switch between v3/v4/v5 displays
  - No layer breakdown view (which features in which layer)
  - No comparison mode
  
- **Should Display:**
  - Dropdown: "Model: v5_elliott_unified"
  - Layer toggle: show only "v4 features" or "Elliott layer features"
  - A/B comparison if models disagree on signal
  - Historical performance by model version
  
- **UI Placement:** Admin panel or settings drawer

#### 7. **Mentor Context Enhancement**
- **What's Missing:**
  - Mentor drawer has placeholder structure but no real data routing
  - No Elliott wave info in mentor reasoning
  - No feature importance in mentor context
  - No model drift info in mentor
  - No multi-TF alignment info
  
- **Should Display:**
  - Updated mentor.js to fetch and render:
    - Current Elliott phase (all TFs)
    - Top 5 active features + weights
    - Model version + calibration status
    - Feature timeline for this symbol
    - Multi-TF alignment score
  
- **Data Source:** MCL backend endpoints (need to be created/exposed)
- **UI Placement:** mentor.js fetch logic + rendering

#### 8. **Training Status Indicator**
- **What's Missing:**
  - No visible indicator that Elliott training is incomplete
  - No "2 missing pointers" warning (1h sell, 5m sell still training)
  - No ETA for repair completion
  - No alert if using fallback model
  
- **Should Display:**
  - Floating badge: "Training: 7/9 models ready ⏳"
  - Click to expand: shows which TFs missing + ETA
  - Alert banner if critical TF missing
  - "Using fallback model" warning if applicable
  
- **UI Placement:** System health panel or floating notification

#### 9. **Chart Layer Controls**
- **What's Missing:**
  - No Elliott wave overlay toggle
  - No feature event markers on chart
  - No Elliott cycle background shading
  - No confidence score display on chart
  
- **Should Add to Chart Controls:**
  - New overlay buttons:
    - "📊 Elliott Waves"
    - "⚖️ Feature Events" (feature trigger markers)
    - "🎨 Confidence Heat" (color intensity = confidence)
  - Layer styling options (color scheme, opacity)
  
- **UI Placement:** chart.js overlay toolbar, similar to MCL

#### 10. **Broker Data Quality Alerts**
- **What's Missing:**
  - No indicator when broker data differs from expected Elliott structure
  - No "chart is stale" alert during broker reconnect
  - No Elliott pattern invalidation warning
  
- **Should Display:**
  - Alert if Elliott wave breaks during data gap
  - "Chart may be inaccurate pending broker reconnect" message
  - Live sync status with model expectations
  
- **UI Placement:** Chart status + health panel

---

## Implementation Priority

### **PHASE 1 (Highest Impact - Start Now)**
1. **Elliott Wave Chart Overlay** (MCL + AstroQuant)
   - Adds visual validation of trained concepts
   - Bridges gap between backend model and frontend
   - ~4-6 hours dev per project

2. **Feature Importance Rankings** (MCL Dashboard)
   - Exposes v4/v5 layer weights
   - Critical for understanding model decisions
   - ~3-4 hours dev

3. **Training Status & Missing Pointer Alerts** (MCL + AstroQuant)
   - Prevents trades on incomplete models
   - Essential for production safety
   - ~2-3 hours dev

### **PHASE 2 (Medium Impact - Follow-up)**
4. **Model Drift Detection UI** (MCL)
   - ~2-3 hours dev

5. **Multi-Timeframe Alignment Matrix** (MCL + AstroQuant)
   - ~4-5 hours dev

6. **Feature Timeline Visualization** (MCL)
   - ~3-4 hours dev

### **PHASE 3 (Nice to Have - Polish)**
7. **v4 vs v5 Layer Toggle** (MCL)
   - ~2-3 hours dev

8. **Elliott Concept Learning Status** (MCL)
   - ~1-2 hours dev

9. **Chart Layer Controls Enhancement** (AstroQuant)
   - ~2-3 hours dev

---

## Backend Endpoints Required

To support frontend displays, create/expose:

```
GET /market_causality/feature_impact_by_timeframe?tf=1h&signal=buy
  Response: { top_features: [...], weights: {...}, version: "v5_elliott_unified" }

GET /market_causality/elliott_wave_state?symbol=XAUUSD&timeframe=1h
  Response: { phase: "impulse", wave_position: 3, confidence: 0.78, alignment_scores: {...} }

GET /market_causality/model_calibration_status
  Response: { version: "v5", status: "CALIBRATED", drift_pct: 5, last_retrain: "2026-04-24T10:00Z" }

GET /market_causality/training_status
  Response: { complete_pointers: {...}, missing_pointers: [...], repair_jobs: [...] }

GET /market_causality/multi_timeframe_alignment?symbol=XAUUSD
  Response: { timeframes: {...}, confluence_score: 0.85, alignment_matrix: {...} }
```

---

## Summary Table

| Aspect | MCL Status | AstroQuant Status | Priority | Dev Hours |
|--------|-----------|-------------------|----------|-----------|
| Elliott Wave Overlay | ❌ Missing | ❌ Missing | HIGH | 4-6 each |
| Feature Importance | ❌ Missing | ❌ Missing | HIGH | 3-4 / 2-3 |
| Model Drift UI | ❌ Missing | ❌ Missing | HIGH | 2-3 each |
| Training Status | ❌ Missing | ❌ Missing | HIGH | 2-3 each |
| Multi-TF Alignment | ❌ Missing | ❌ Missing | MEDIUM | 4-5 each |
| Feature Timeline | ❌ Missing | ❌ Missing | MEDIUM | 3-4 / 2-3 |
| v4/v5 Layer Toggle | ❌ Missing | ❌ Missing | MEDIUM | 2-3 each |
| Chart Overlays | ✓ Extensive | ✓ Basic | MEDIUM | 2-3 each |
| Gann/Astro Display | ✓ Complete | ✓ Basic | COMPLETE | -- |
| ICT Visualization | ✓ Partial | ✓ Partial | LOW | 1-2 each |

---

## Next Steps

1. **Approve priorities** - Which features most critical for your workflow?
2. **Create backend endpoints** - Elliott state, feature impact, model status
3. **Begin PHASE 1 implementation** - Elliott overlay + feature importance
4. **Integration testing** - Verify frontend/backend data flow
5. **Deploy to MCL, then AstroQuant** - Stagger rollout for stability

**Estimated Total Dev Time (All Phases):** ~40-50 hours across both projects

---

*Generated by: Frontend Aspect Audit | v4: 120 features | v5: 135 features + Elliott*
