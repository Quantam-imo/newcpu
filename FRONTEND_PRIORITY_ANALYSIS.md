# Frontend Priority Analysis & Sequencing
**Prepared:** 2026-04-24 | **Context:** v4 (120 features) + v5 Elliott (135 features) trained, 2 pointers in repair

---

## Current State Assessment

### Training Readiness
| Timeframe | v5 Elliott | Status | Model Active |
|-----------|-----------|--------|-------------|
| 1d | ✓ Complete | Ready | v5_elliott_unified |
| 4h | ✓ Complete | Ready | v5_elliott_unified |
| 1h | ⏳ Repairing | ~36 min elapsed | Fallback to v4 |
| 30m | ⏳ Repairing | ~36 min elapsed | Fallback to v4 |
| 15m | ⏳ Repairing | ~36 min elapsed | Fallback to v4 |
| 5m | ⏳ Repairing | ~36 min elapsed | Fallback to v4 |
| 1m | Earlier session | Not ready | Fallback to v3 |

**Key Constraint:** 2 missing pointers (1h sell, 5m sell) still training. No UI alerts about this.

---

## Feature Priority Matrix

### HIGH PRIORITY (Unblock Production, Safety-Critical)

#### 1️⃣ **Training Status & Missing Pointer Alerts** 
**Why it's #1:**
- 🚨 **Safety-critical:** Prevents accidental trades on incomplete models
- ⏱️ **Immediate value:** Shows exactly which TFs are ready vs. fallback
- 🔴 **Risk if skipped:** Might trade 5m signals on v3 thinking it's v5 Elliott
- 🎯 **Solves current blocker:** User doesn't know 1h/5m pointers still training

**What it displays:**
```
✅ Status Badge in header:
   "Training: 7/9 models ready ⏳ | v5 Elliott (1d✓ 4h✓) | v4 Fallback (1h⏳ 30m⏳ 15m⏳ 5m⏳)"

✅ Expandable alert:
   Missing Pointers:
   - 1h__all_bars__first_touch_sell (PID 5419, elapsed 36:22)
   - 5m__all_bars__first_touch_sell (PID 5400, elapsed 36:22)
   ETA: Monitor or force retry

✅ Color coding:
   - Green = v5 Elliott ready
   - Yellow = v4 fallback (safe but older)
   - Red = Critical missing (1h/5m)
```

**Dev Effort:** 2-3 hours (both MCL + AQ)
- MCL: Add query endpoint to training registry, render status badge
- AQ: Consume MCL endpoint, display in system health panel

**Dependencies:** None (uses existing training logs)

**Timeline Impact:** 🟢 FAST — can deploy same day

---

#### 2️⃣ **Elliott Wave Chart Overlay** 
**Why it's #2:**
- 💰 **Highest ROI:** v5 Elliott trained and ready for 1d/4h—should be visible
- 👀 **Visual validation:** See if Elliott patterns actually match market structure
- 📊 **Bridges gap:** Backend model → frontend reality check
- 🎯 **Workflow alignment:** User mentioned Elliott as core concept

**What it displays:**
```
Chart Overlay (toggle on/off):
- Impulse phases: light green background
- Corrective phases: light red background  
- Wave labels at swing points (Wave 1, Wave 2, etc.)
- Confidence badge: "Wave 3 | Confidence 78%"
- Progress bar: "38% into Wave formation"

Controls:
- "📊 Elliott Waves" toggle button
- "🔢 Wave Labels" sub-toggle
- "📈 Phase Shading" sub-toggle
- "⚖️ Confidence Heat" (intensity = confidence)

Multi-TF view (MCL):
- Sidebar: 1d Elliott | 4h Elliott | 1h Elliott (fallback v4)
- Alignment indicator: ✓ all phases match OR ✗ 1h diverges
```

**Dev Effort:** 4-6 hours per project
- Canvas drawing + overlay logic: 3-4h
- Data fetching from backend: 1-2h
- Integration testing: 1h

**Dependencies:** 
- Needs `/market_causality/elliott_wave_state` backend endpoint (to create)
- Requires MCL scanner.py to expose Elliott data via API

**Timeline Impact:** 🟡 MEDIUM — backend endpoint creation adds complexity

---

#### 3️⃣ **Feature Importance Ranking Display** 
**Why it's #3:**
- 🧠 **Decision transparency:** "Why did the model say BUY?"
- 📊 **Learning tool:** See which features actually work
- 🔍 **Debugging:** Identify if model is behaving as expected
- 🎯 **A/B value:** Compare v4 (Gann/Astro/ICT) vs v5 (+ Elliott) feature weights

**What it displays:**
```
MCL Dashboard - New Panel "⚖️ Feature Importance":

Table view:
| Rank | Feature | Layer | Weight | Timeframe | Impact % | Trend |
|------|---------|-------|--------|-----------|----------|-------|
| 1    | nakshatra | Astro | 0.0847 | 1h        | 12.5%    | ↑ +2% |
| 2    | square    | Astro | 0.0756 | 1h        | 11.1%    | ↓ -1% |
| 3    | opposition| Astro | 0.0692 | 1h        | 10.2%    | ↔ 0%  |
| ...  | ...     | ...   | ...    | ...       | ...      | ...   |

AstroQuant Mentor Drawer - New Tab "Features":
- Compact list (top 5 by weight)
- Current signal contribution % per feature
- Color-coded by layer (Astro=purple, Gann=orange, Elliott=green, ICT=blue)
- Clickable to see full ranked list
```

**Dev Effort:** 3-4 hours (MCL) + 2-3 hours (AQ)
- MCL: Query feature impact, render table, sorting logic
- AQ: Consume MCL endpoint, Mentor panel layout
- Backend: Expose existing ASPECT_FEATURE_IMPACT_REPORT data via API

**Dependencies:**
- Needs `/market_causality/feature_impact_by_timeframe` backend endpoint
- Data already exists in reports, just needs API exposure

**Timeline Impact:** 🟢 FAST — data exists, just needs API wrapper + UI

---

### MEDIUM PRIORITY (Operational Visibility, Nice-to-Have)

#### 4️⃣ **Model Drift Detection UI**
**Why it's important (but not urgent):**
- 🔍 **Early warning:** Catch model degradation before it affects trades
- 📉 **Calibration indicator:** Know if model is still trustworthy
- 🎯 **Version tracking:** Clear indication of active model version
- ⚠️ **Risk mitigation:** Avoid trading on stale models

**What it displays:**
```
Header Badge: "Model: v5_elliott_unified ✓ CALIBRATED" (green)
   OR "Model: v4_layered_execution ⚠️ DRIFTED (8% weight shift)" (yellow)
   OR "Model: v3_amd_cycle_state ❌ STALE (4 days old)" (red)

Status Breakdown:
- Active Version: v5_elliott_unified
- Last Retrain: 2026-04-24 10:15 UTC (9 min ago)
- Feature Weight Drift: +2.3% from baseline (acceptable)
- Confidence: 94% (high)
- Next Auto-Retrain: 2026-04-25 02:00 UTC

Alert Threshold Crossed:
- If drift > 10%: ⚠️ banner "Model drifted beyond tolerance — retrain recommended"
- If stale > 24h: ❌ banner "Model is outdated — retrain immediately"
- If pointer missing: 🚨 banner "Critical pointer missing — switch to fallback"
```

**Dev Effort:** 2-3 hours per project
- Status dashboard query: 1h
- Badge/banner rendering: 1h
- Alert logic: 1h

**Dependencies:**
- Needs training registry to track retrain timestamps
- Needs baseline weights stored for comparison

**Timeline Impact:** 🟡 MEDIUM — requires some backend instrumentation

---

#### 5️⃣ **Multi-Timeframe Elliott Alignment Matrix**
**Why it's useful (but not urgent):**
- 🎯 **Confluence view:** "How many TFs agree on Elliott phase?"
- 🔀 **Conflict detector:** Flags when 1d impulse but 1h correction
- 📊 **Cascading validation:** 1m→5m→15m→1h→4h→1d agreement chain
- 💡 **Decision support:** Use alignment % to adjust position sizing

**What it displays:**
```
MCL Dashboard - New Section "Multi-TF Elliott Alignment":

Matrix:
| TF   | Elliott Phase | Gann Angle | Astro Event | ICT Status | Alignment |
|------|--------------|-----------|-------------|-----------|-----------|
| 1d   | Impulse 3    | 45°       | Full Moon   | Active    | ✓         |
| 4h   | Impulse 3    | 90°       | ---         | Active    | ✓         |
| 1h   | Correction   | 180°      | ---         | Pending   | ✗ DIVERGE |
| 15m  | Impulse 1    | 45°       | ---         | Pending   | ✗ DIVERGE |
| 5m   | Impulse 1    | 22.5°     | ---         | Pending   | ✗ DIVERGE |

Confluence Score: 40% (2/5 TFs in impulse phase)
Signal Strength: WEAK (disagreement across timeframes)
Recommendation: Wait for 1h to confirm impulse phase before entry
```

**Dev Effort:** 4-5 hours per project
- Data aggregation logic: 2h
- Matrix rendering: 1.5h
- Confluence scoring algorithm: 1h
- Integration: 0.5h

**Dependencies:**
- Needs multi-TF Elliott state endpoint
- Requires all TF data to be queried in parallel

**Timeline Impact:** 🟡 MEDIUM — complex data aggregation

---

### LOWER PRIORITY (Polish, Nice-to-Have)

#### 6️⃣ **Feature Timeline Visualization**
**Why it's lower priority:**
- 📈 **Learning value:** See which features drove past wins
- 📊 **Pattern recognition:** Identify winning feature combinations
- ⏱️ **Post-hoc analysis:** Only useful after trades close
- 🟡 **Medium effort for limited immediate impact**

**Dev Effort:** 3-4 hours (MCL) + 2-3 hours (AQ)
**Timeline Impact:** Slow—medium complexity for analytical use

---

#### 7️⃣ **v4 vs v5 Layer Toggle**
**Why it's lower priority:**
- 🔄 **Comparison tool:** A/B test v4 vs v5 feature importance
- 🧪 **Experimental:** Nice for dev/testing, less critical for production
- 📊 **Layer breakdown:** See feature distribution per concept
- 🟡 **Medium effort, educational value**

**Dev Effort:** 2-3 hours per project
**Timeline Impact:** Medium—mostly UI conditionals

---

#### 8️⃣ **Enhanced Chart Layer Controls**
**Why it's lower priority:**
- 🎨 **Customization:** Color schemes, opacity, layer visibility
- 👀 **Visual polish:** Better overlay organization
- 📊 **Quality of life:** Easier to manage overlays
- 🟢 **Low effort, high UX value**

**Dev Effort:** 2-3 hours per project
**Timeline Impact:** Fast—UI polish only

---

## Recommended Sequencing Scenarios

### **SCENARIO A: Speed-to-Market (Production ASAP)**
*Optimal if: You want to go live ASAP with safety nets*

**Deployment Schedule:**
```
Week 1 (Apr 24-28):
  Day 1-2: Training Status Alerts + Missing Pointer UI (SPRINT)
    - Deploy to MCL + AQ
    - Verify repair training completion
    - Clear missing pointer issues OR alert users

  Day 3-4: Elliott Wave Overlay (HIGH IMPACT)
    - Create backend endpoint
    - Draw overlay logic
    - Deploy to 1d/4h first (already trained)

  Day 5: Feature Importance Ranking (TRANSPARENCY)
    - API endpoint for feature weights
    - MCL dashboard table
    - AQ Mentor panel tab

Week 2 (May 1-5):
  Model Drift UI + Multi-TF Alignment (POLISH)

Timeline: 🟢 Production ready in 1 week
Risk: ⚠️ No drift detection until Week 2
```

**Go-Live Readiness:** 
- ✓ Know model status (1h/5m training tracked)
- ✓ See Elliott phases (visual validation)
- ✓ Understand decisions (feature rankings)
- ⚠️ No drift warning until Week 2

---

### **SCENARIO B: Robust & Safe (Production + Confidence)**
*Optimal if: You can wait 2 weeks, want maximum safety*

**Deployment Schedule:**
```
Week 1 (Apr 24-28):
  Day 1: Training Status Alerts (SAFETY CRITICAL)
    - Must-have before going live
    - Prevents blind trades on incomplete models

  Day 2-3: Model Drift Detection UI (CONFIDENCE)
    - Know if model is trustworthy
    - Clear indicator of version/calibration

  Day 4-5: Elliott Wave Overlay (VALIDATION)
    - See if Elliott patterns match reality
    - Confidence boost before execution

Week 2 (May 1-5):
  Day 1-2: Feature Importance Ranking (TRANSPARENCY)
    - Understand decisions
    - Debug anomalies

  Day 3-4: Multi-TF Elliott Alignment (CONFLUENCE)
    - See agreement across TFs
    - Better position sizing logic

  Day 5: Testing + Documentation

Timeline: 🟡 Production ready in 2 weeks
Risk: ✓ Minimal—all safety nets in place
Confidence: ✓ Maximum—see all decision logic
```

**Go-Live Readiness:**
- ✓ Know model status + drift detection
- ✓ See Elliott phases + drift warnings
- ✓ Understand decisions + feature rankings
- ✓ Multi-TF alignment for better confluence

---

### **SCENARIO C: Balanced (Best Value/Effort)**
*Optimal if: You want solid production capability in 1 week, with room for enhancements*

**Deployment Schedule:**
```
PHASE 1 (Apr 24-26) — MUST-HAVES:
  1. Training Status & Missing Pointer Alerts (2-3h)
  2. Model Drift Detection UI (2-3h)

PHASE 2 (Apr 27-28) — HIGH-VALUE:
  3. Elliott Wave Overlay (4-6h, split MCL 1st)
  4. Feature Importance Ranking (3-4h)

POST-LAUNCH (May 1+) — NICE-TO-HAVE:
  5. Multi-TF Alignment Matrix (4-5h)
  6. Feature Timeline (3-4h)

Timeline: 🟢 Live in 4 days with safety + visibility
Enhancements: Ongoing after launch
```

**Go-Live Readiness:**
- ✓ Safe (training status tracked)
- ✓ Confident (drift detection active)
- ✓ Visible (Elliott overlays + feature weights)
- 🟡 Alignment matrix can wait (lower impact)

---

## Decision Framework: Pick Your Scenario

### Ask Yourself:

**Q1: How soon do you need to go live?**
- "ASAP (this week)" → Scenario A
- "Can wait 2 weeks" → Scenario B
- "Balanced in ~4 days" → Scenario C ⭐ **RECOMMENDED**

**Q2: What's your biggest current blocker?**
- "Don't know if models are training/ready" → Start with #1 (Training Status)
- "Want to see Elliott on chart" → Start with #2 (Elliott Overlay)
- "Need to understand model decisions" → Start with #3 (Feature Importance)

**Q3: How much operational overhead can you tolerate?**
- "I need full safety nets" → Add Model Drift UI (#4)
- "I need 360° visibility" → Add Multi-TF Alignment (#5)
- "Just keep me safe and show basics" → Skip nice-to-haves, do PHASE 1 + 2

**Q4: Which timeframes matter most for your trading?**
- "1d/4h only" → Elliott overlay ready immediately (both trained)
- "Scalp 5m-1h" → Focus on #1 (Training Status) + #4 (Model Drift)—repair jobs critical
- "All TFs" → Need all features, recommend Scenario C

---

## My Recommendation: **Scenario C (Balanced)**

**Why:**
1. ✅ **Training Status Alerts first** (2-3h) — Safety-critical, unblocks you
2. ✅ **Model Drift UI second** (2-3h) — Confidence boost, early warning
3. ✅ **Elliott Overlay third** (4-6h) — Visual validation of trained concept
4. ✅ **Feature Importance fourth** (3-4h) — Decision transparency
5. 🟡 **Multi-TF Alignment later** (4-5h) — Post-launch enhancement

**Deployment:** Go live Day 4 with solid foundation, keep iterating

**Effort:** ~14-18 hours total split across MCL + AQ
**Timeline:** 4-5 days
**Risk:** Minimal (all safety nets in place)
**Confidence:** High (visible decision logic + drift detection)

---

## Next Steps to Confirm

1. **Which scenario appeals to you?** (A / B / C)
2. **What's your timeline?** (ASAP / 2 weeks / flexible)
3. **Priority for your workflow:** 
   - Safety first (know model status) 
   - Visibility first (see Elliott patterns)
   - Transparency first (understand decisions)
4. **Can you confirm the 2 missing pointers (1h sell, 5m sell) are still repairing?**
   - If YES → #1 (Training Status) is critical blocker
   - If NO (they completed) → #2 (Elliott Overlay) becomes #1

Once you confirm, I'll start implementation immediately. ⚡

