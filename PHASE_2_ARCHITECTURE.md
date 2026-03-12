# PHASE 2: Caching & Performance Architecture

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER REQUEST (GET /mentor/context)              │
└────────────────────────────────────┬──────────────────────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │  Check localStorage Cache?      │
                    │  Key: AQ_CACHE_/mentor/...      │
                    │  (performanceMs: 0-1ms)         │
                    └────┬──────────┬──────────────┘
                         │ HIT      │ MISS
          ┌──────────────▼┐  ┌──────▼──────────────────┐
          │ Return Cached  │  │ Start Multi-Origin     │
          │ Response       │  │ Network Fallback       │
          │ (X-From-Cache) │  │ Targets:               │
          │ trackPerf(0ms) │  │ 1. /path (relative)    │
          │                │  │ 2. localhost:8000      │
          └────────┬───────┘  │ 3. 127.0.0.1:8000      │
                   │          │ timeout: 25-30s        │
                   │          │ trackPerf(startTime→)  │
                   │          └────────┬───────────────┘
                   │                   │
                   │          ┌────────▼────────────────┐
                   │          │   Successful Response?  │
                   │          │   (200 OK or 599 error) │
                   │          └────┬───────────┬────────┘
                   │               │ YES       │ NO
                   │        ┌──────▼─────┐  ┌─▼──────────────┐
                   │        │ Cache JSON  │  │ Show Error     │
                   │        │ in Storage  │  │ Banner+Retry   │
                   │        │ (if in      │  │ Return 599     │
                   │        │ CACHE_      │  └────────────────┘
                   │        │ CONFIG)     │
                   │        └─────┬───────┘
                   │              │
                   └──────────────┼──────────────┐
                                  │              │
                    ┌─────────────▼────────┐  ┌─▼─────────────────┐
                    │ Return Response to   │  │ Performance Metrics│
                    │ Calling Code         │  │ Tracking          │
                    │ (mentor.js/chart.js) │  │ {path,duration,   │
                    │                      │  │  fromCache,ts}    │
                    └──────────────────────┘  └───────────────────┘
```

## Data Flow: Caching Mechanism

### Request Path (First Load):
```
GET /mentor/context?symbol=XAUUSD
    ↓
Cache Key: "AQ_CACHE_/mentor/context?symbol=XAUUSD"
    ↓
localStorage.getItem(cacheKey) → null
    ↓
Fetch from http://127.0.0.1:8000/mentor/context?symbol=XAUUSD [7400ms]
    ↓
Parse JSON response
    ↓
Store in localStorage: {
  data: {...},
  timestamp: 1710154200000,
  ttl: 8000,
  size: 1234
}
    ↓
Return Response object
```

### Request Path (Cache Hit - within 8s):
```
GET /mentor/context?symbol=XAUUSD
    ↓
Cache Key: "AQ_CACHE_/mentor/context?symbol=XAUUSD"
    ↓
localStorage.getItem(cacheKey) → Found!
    ↓
age = Date.now() - 1710154200000 = 1500ms (< 8000ms TTL)
    ↓
Cache valid! Return immediately [<1ms]
    ↓
trackPerformance(path, 0, true) ← Marks as cache hit
```

### Request Path (Cache Expired):
```
GET /mentor/context?symbol=XAUUSD
    ↓
Cache Key: "AQ_CACHE_/mentor/context?symbol=XAUUSD"
    ↓
localStorage.getItem(cacheKey) → Found!
    ↓
age = Date.now() - 1710154200000 = 9500ms (> 8000ms TTL)
    ↓
Cache expired! localStorage.removeItem(cacheKey)
    ↓
Return null → Fetch from network (same as first load)
```

## Cache Configuration Schema

```javascript
CACHE_CONFIG = {
  "/endpoint/path": {
    ttl: 5000,           // Time-to-live in milliseconds
    maxSize: 100         // Max entries (currently unused)
  },
  ...
}

// Example: Mentor caching config
"/mentor/context": {
  ttl: 8000,    // 8 seconds (matches polling interval)
  maxSize: 100  // Future: limit concurrent cached symbols
}
```

## Performance Metrics Structure

```javascript
performanceMetrics = {
  // All requests in current session (last 100 kept)
  requests: [
    {
      path: "/mentor/context",     // Request path (without query params)
      duration: 7420,              // Total time in milliseconds
      fromCache: false,            // true = cache hit, false = network
      timestamp: 1710154200000     // When request completed
    },
    {
      path: "/chart/data",
      duration: 0,                 // Cache hit shows 0ms
      fromCache: true,
      timestamp: 1710154205000
    },
    // ... up to 100 entries
  ],
  
  // Slowest endpoint per unique path
  slowestEndpoints: {
    "/mentor/context": 7420,       // Worst-case duration
    "/chart/data": 5200,
    "/market/offset_quality": 18400
  }
}

// Summary function output:
getPerformanceSummary() → {
  totalRequests: 42,
  averageByPath: {
    "/mentor/context": 2500,       // Average (first hit + cached)
    "/chart/data": 1200,           // Average
  },
  slowestEndpoints: { ... },       // Copy of slowestEndpoints
  lastUpdated: "2026-03-11T15:31:00Z"
}
```

## Performance Dashboard State Machine

```
Page Load
    ↓
Dashboard hidden
    ↓
┌────────────────────────────────┐
│ User clicks "📊 Perf" button   │
└────────┬───────────────────────┘
         │
         ↓
┌────────────────────────────────┐
│ perfDash.classList.toggle(...)  │
└────┬───────┬──────────────────┘
     │       │
Hidden│       │ Show
      │       ↓
      │   ┌──────────────────────┐
      │   │ updatePerfDashboard()│
      │   │ - Get metrics summary │
      │   │ - Build table         │
      │   └────────┬─────────────┘
      │            │
      │            ↓
      │   ┌──────────────────────┐
      │   │ updateCacheStatus()  │
      │   │ - List cache entries  │
      │   │ - Show ✓/∅ status    │
      │   └────────┬─────────────┘
      │            │
      │            ↓
      │        Dashboard Visible
      │
      └────────────────────────────┘
```

## Integration Points

### api.js Integration:
```javascript
// Early: Define cache system
const CACHE_CONFIG = { ... }
const performanceMetrics = { ... }
function getCachedResponse(path) { ... }
function cacheResponse(path, data) { ... }
function trackPerformance(path, duration, fromCache) { ... }

// In apiFetch():
// 1. Check cache before loop
const cached = getCachedResponse(path);
if (cached) return cached;

// 2. Track performance after fetch
const duration = performance.now() - startTime;
trackPerformance(path, duration, false);

// 3. Cache successful responses
if (response.ok) {
  const jsonData = await response.clone().json();
  if (CACHE_CONFIG[pathBase]) {
    cacheResponse(path, jsonData);
  }
}

// Late: Initialize dashboard
function initPerfDashboard() { ... }
initPerfDashboard();
```

### mentor.js Integration:
```javascript
// Same pattern as api.js
const mentorFetch = async (path, options, timeoutMs = 25000) => {
  // Check cache first
  const cached = getCachedResponse(path);  // From api.js
  if (cached) return ...;
  
  // ... fetch logic ...
  
  // Track performance
  trackPerformance(path, duration, false);  // From api.js
  
  // Cache response
  if (CACHE_CONFIG[pathBase]) {
    cacheResponse(path, jsonData);  // From api.js
  }
}
```

### chart.js Integration:
```javascript
// Same pattern in fetchJson()
async function fetchJson(url, timeoutMs = 30000) {
  // Check cache first
  const cached = getCachedResponse(url);  // From api.js
  if (cached) return cached;
  
  // ... fetch logic ...
  
  // Track performance
  trackPerformance(url, duration, false);  // From api.js
  
  // Cache response
  if (CACHE_CONFIG[urlPath]) {
    cacheResponse(url, jsonData);  // From api.js
  }
}
```

## Browser Storage Details

### localStorage Keys Pattern:
```
AQ_CACHE_/mentor/context?symbol=XAUUSD
AQ_CACHE_/mentor/context?symbol=GC.FUT
AQ_CACHE_/chart/data?symbol=XAUUSD&timeframe=1m&limit=80
AQ_CACHE_/chart/data?symbol=GC.FUT&timeframe=1m&limit=80
AQ_CACHE_/status
```

### Storage Quota Typical Values:
- Chrome/Edge: ~10MB per domain
- Firefox: ~10MB per domain
- Safari: ~5MB per domain
- Graceful fallback: If write fails, skip caching

### Example: Full Cache Entry Structure
```javascript
// localStorage["AQ_CACHE_/mentor/context?symbol=XAUUSD"] =
{
  "data": {
    "symbol": "XAUUSD",
    "context": { "price": 2050.50, ... },
    "iceberg": { "strength": "strong", ... },
    // ... full API response
  },
  "timestamp": 1710154200123,  // ms since epoch
  "ttl": 8000,                  // milliseconds
  "size": 1234                  // bytes
}
```

## Error Handling in Caching Context

```
Try to cache response
    ↓
localStorage.setItem(key, JSON.stringify(entry))
    ↓
┌────────────┬────────────────┐
│ Success    │ Failure (quota │
└──┬─────────┴────────────────┘
   │
Response returned regardless
(caching failure ≠ request failure)

Graceful: If localStorage unavailable:
- Logging: console.warn()
- Behavior: Requests still work, just no caching
```

## Summary: Request Flow with Caching

1. **Check Phase** (1ms): Look for valid cached entry
2. **Hit Phase** (<1ms): Return cached data if valid
3. **Miss Phase** (3-20s): Multi-origin network fallback
4. **Track Phase** (1ms): Record metrics (duration, cache status)
5. **Store Phase** (1ms): Save successful response to cache
6. **Return Phase** (instant): Return response to calling code

**Total improvement**: 85-99% latency reduction for cache hits
