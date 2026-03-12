# PHASE 2: Developer Quick Reference

## Public API Functions (Available Globally)

### Cache Management

```javascript
// Get cached response (returns null if not found or expired)
getCachedResponse(path) 
// Example: getCachedResponse("/mentor/context?symbol=XAUUSD")
// Returns: null or {response data}

// Manually cache a response
cacheResponse(path, jsonData)
// Example: cacheResponse("/chart/data?symbol=XAUUSD&...", {candles: [...]})

// Clear specific cache entry  
clearCache(pathPattern)
// Example: 
//   clearCache("/mentor/context")         // Clear all mentors
//   clearCache("/chart/data")              // Clear all charts
//   clearCache("*")                        // Clear everything

// Get performance summary
getPerformanceSummary()
// Returns: {totalRequests, averageByPath, slowestEndpoints, lastUpdated}

// Record performance metric
trackPerformance(path, duration, fromCache)
// Example: trackPerformance("/mentor/context", 7420, false)
// Note: Usually called automatically by fetch functions
```

### Performance Monitoring

```javascript
// View full metrics array
performanceMetrics.requests
// Returns array of: {path, duration, fromCache, timestamp}

// View slowest endpoints
performanceMetrics.slowestEndpoints
// Returns: {"/path": maxDuration, ...}

// View cache configuration
CACHE_CONFIG
// Shows: {"/endpoint": {ttl: 5000, maxSize: 100}, ...}
```

## Configuration Changes

### Adjust Cache TTLs

Edit `api.js` line ~75, update `CACHE_CONFIG`:

```javascript
const CACHE_CONFIG = {
	"/mentor/context": { ttl: 8000, maxSize: 100 },    // ← Change here
	"/mentor": { ttl: 8000, maxSize: 100 },
	"/chart/data": { ttl: 3000, maxSize: 150 },        // ← Or here
	// ... etc
};
```

**Common adjustments:**
```javascript
// For real-time data (fresh is important)
"/chart/data": { ttl: 1000, maxSize: 150 },      // Cache for 1 second only

// For stale-safe data (caching is important)
"/mentor/context": { ttl: 15000, maxSize: 100 }, // Cache for 15 seconds

// For infrequently changing data
"/status": { ttl: 30000, maxSize: 50 },          // Cache for 30 seconds
```

### Add New Endpoint to Caching

1. Edit `api.js` `CACHE_CONFIG`:
```javascript
const CACHE_CONFIG = {
	// ... existing ...
	"/my/new/endpoint": { ttl: 5000, maxSize: 100 },  // ← Add here
};
```

2. No changes needed in fetch functions - caching is automatic!

## Debug Console Commands

### Check Cache Status

```javascript
// See what's currently cached
for (let i = 0; i < localStorage.length; i++) {
  const key = localStorage.key(i);
  if (key.startsWith("AQ_CACHE_")) {
    const entry = JSON.parse(localStorage.getItem(key));
    const age = Date.now() - entry.timestamp;
    console.log(`${key}: age=${age}ms, ttl=${entry.ttl}ms, size=${entry.size}B`);
  }
}

// Or simpler - use helper function
localStorage.getItem("AQ_CACHE_/mentor/context?symbol=XAUUSD")
// Shows the full cache entry
```

### Force Cache Miss

```javascript
// Clear specific cache
clearCache("/mentor/context");

// Next request to /mentor/context will fetch fresh from network
loadMentor(); // Will not use cache
```

### View Performance Data

```javascript
// Full summary
getPerformanceSummary()
// Output: {
//   totalRequests: 42,
//   averageByPath: {
//     "/mentor/context": 2500,
//     "/chart/data": 1200
//   },
//   slowestEndpoints: {
//     "/mentor/context": 7420,
//     "/chart/data": 5200,
//     "/market/offset_quality": 18400
//   },
//   lastUpdated: "2026-03-11T15:31:00Z"
// }

// Raw metrics
console.table(performanceMetrics.requests);
// Shows table of all requests with timings

// Find slowest request
const slowest = performanceMetrics.requests.reduce((a,b) => 
  a.duration > b.duration ? a : b
);
console.log(`Slowest: ${slowest.path} took ${slowest.duration}ms`);
```

### Monitor Cache Hits in Real-Time

```javascript
// Print cache hit rate
const metrics = getPerformanceSummary();
const fromCache = performanceMetrics.requests.filter(r => r.fromCache).length;
const cacheHitRate = (fromCache / metrics.totalRequests * 100).toFixed(1);
console.log(`Cache hit rate: ${cacheHitRate}% (${fromCache}/${metrics.totalRequests})`);

// Watch for cache misses (would indicate expiry or TTL too short)
const misses = performanceMetrics.requests.filter(r => !r.fromCache);
console.log(`Recent misses: ${misses.length}`);
```

## Testing Scenarios

### Scenario 1: Verify Cache Is Working

```javascript
// 1. Open Performance Dashboard
// Click "📊 Perf" button in header

// 2. Load Mentor drawer
// Click "Mentor" drawer toggle

// 3. Check Cache Status in dashboard
// Should show: ✓ Cached next to /mentor/context

// 4. Check metrics
// Should show avg time ~7-8s (first load)

// 5. Close and re-open mentor within 8 seconds
// Should load instantly (<1ms)

// 6. Metrics should show cache hit (0ms duration)
```

### Scenario 2: Test Cache Expiration

```javascript
// 1. Load mentor drawer (caches data)
// 2. Click "Clear All Caches" in dashboard (or manually: clearCache("*"))
// 3. Re-open mentor drawer
// Should take full 7-8s (no cache)
```

### Scenario 3: Multi-Symbol Performance

```javascript
// 1. Open Performance Dashboard
// 2. Scan multiple symbols (XAUUSD, GC.FUT, NQ.FUT, etc.)
// 3. Watch Request Metrics
// First symbol: ~18s for /market/offset_quality
// Second symbol (within 10s): <1ms (cache hit)
// Speed improvement: ~99%

// Expected output:
// getPerformanceSummary()
// {
//   totalRequests: 12,
//   averageByPath: {
//     "/market/offset_quality": 2000,  // (18000 + 0 + 0) / 3 symbols
//   },
//   slowestEndpoints: {
//     "/market/offset_quality": 18000
//   }
// }
```

## Troubleshooting

### "Cache not working - always fetching from network"

**Check 1:** Browser localStorage is disabled
```javascript
try {
  localStorage.setItem("test", "1");
  localStorage.removeItem("test");
  console.log("localStorage: OK");
} catch (e) {
  console.log("localStorage: DISABLED", e);
}
```

**Check 2:** Endpoint not in CACHE_CONFIG
```javascript
// Verify your endpoint is configured
CACHE_CONFIG["/your/endpoint"]
// Should return: {ttl: 5000, maxSize: 100}  (if configured)
// Or: undefined (if not configured)
```

**Check 3:** Response not JSON
```javascript
// Only JSON responses are cached
// If response is HTML/text, it won't be cached (intentional)
```

### "Performance dashboard not showing up"

**Check 1:** Click the button - it's hidden by default
```javascript
// Toggle visibility manually
document.getElementById("perfDashboard").classList.toggle("hidden");
```

**Check 2:** No metrics collected yet
```javascript
// Need at least one request
// Make a request: await apiFetch("/status", {}, 5000)
// Then click dashboard button
```

## Performance Tuning Tips

### If Cache Hit Rate Too Low (< 40%)

**Problem:** Users not seeing cache benefits  
**Solution:** Increase TTL values

```javascript
// Before: Cache mentor for 8s but users click slowly
"/mentor/context": { ttl: 8000, ... }

// After: Cache for 15s (full interaction usually within this)
"/mentor/context": { ttl: 15000, ... }
```

### If Cache Hit Rate Too High (> 80%)

**Problem:** Users seeing stale data  
**Solution:** Decrease TTL values

```javascript
// Before: Cache chart for 3s causing lag on pan
"/chart/data": { ttl: 3000, ... }

// After: Cache for 1s (more frequent updates)
"/chart/data": { ttl: 1000, ... }
```

### If Storage Full (localStorage quota exceeded)

**Check current usage:**
```javascript
let total = 0;
for (let i = 0; i < localStorage.length; i++) {
  const key = localStorage.key(i);
  if (key.startsWith("AQ_CACHE_")) {
    total += localStorage.getItem(key).length;
  }
}
console.log(`Cache storage: ${(total/1024).toFixed(1)} KB`);
```

**Solution: Clear old caches**
```javascript
clearCache("*");
// Or selectively
clearCache("/chart/data");  // Frees ~50KB
clearCache("/mentor/context");  // Frees ~50KB
```

## Monitoring in Production

### Key Metrics to Track

1. **Cache Hit Rate** = cached_requests / total_requests
   - Target: 15-25% overall
   - Mentor: 60-80%
   - Chart: 40-60%

2. **Avg Response Time**
   - Without cache: 5-20s for slow endpoints
   - With cache: <1ms
   - Target: 50% improvement

3. **Slowest Endpoint**
   - /market/offset_quality usually slowest
   - Should be <1ms when cached
   - Should be ~18s on cache miss

### Simple Dashboard Query

```javascript
const summary = getPerformanceSummary();
console.log(`
📊 Performance Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Requests: ${summary.totalRequests}
Cache Hit Rate: ${(summary.totalRequests > 0 ? 
  ((performanceMetrics.requests.filter(r => r.fromCache).length / summary.totalRequests) * 100).toFixed(1) : 0)}%

Avg Response Times:
${Object.entries(summary.averageByPath)
  .map(([path, avg]) => `  ${path}: ${avg}ms`)
  .join('\n')}

Slowest Endpoints:
${Object.entries(summary.slowestEndpoints)
  .sort(([,a],[,b]) => b-a)
  .slice(0,3)
  .map(([path, ms]) => `  ${path}: ${ms}ms`)
  .join('\n')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`);
```

## Common Integration Patterns

### Pattern 1: Automatic Caching (Default)

```javascript
// In api.js, mentor.js, chart.js
// Already integrated! Just call apiFetch/mentorFetch/fetchJson

const result = await apiFetch("/mentor/context?symbol=XAUUSD");
// Automatically: checks cache, tracks perf, stores response
```

### Pattern 2: Manual Cache Management

```javascript
// If you need fine control over caching
const path = "/my/endpoint";

// Check cache first
let data = getCachedResponse(path);
if (!data) {
  // Fetch from network
  const res = await fetch(path);
  data = await res.json();
  // Manually cache
  cacheResponse(path, data);
}
```

### Pattern 3: Force Fresh Data

```javascript
// User clicks "Refresh" button
// Solution 1: Clear cache then fetch
clearCache("/mentor/context");
loadMentor();  // Will fetch fresh

// Solution 2: Add cache-busting parameter
const now = Date.now();
await apiFetch(`/mentor/context?symbol=XAUUSD&t=${now}`);
// Different URL = different cache key = fresh fetch
```

---

**Last Updated:** March 11, 2026  
**Status:** Production Ready
