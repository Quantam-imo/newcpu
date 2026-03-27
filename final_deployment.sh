#!/bin/bash

# DEPLOYMENT VALIDATION & PACKAGE GENERATOR
# Prepares system for live trading deployment
# Usage: bash final_deployment.sh [validate|package|both]

set -e

COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_NC='\033[0m' # No Color

REPO_ROOT="/workspaces/newcpu"
LOG_FILE="${REPO_ROOT}/deployment_$(date +%Y%m%d_%H%M%S).log"

log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

check_passed() {
    echo -e "${COLOR_GREEN}✓${COLOR_NC} $1" | tee -a "$LOG_FILE"
}

check_warning() {
    echo -e "${COLOR_YELLOW}⚠${COLOR_NC} $1" | tee -a "$LOG_FILE"
}

check_failed() {
    echo -e "${COLOR_RED}✗${COLOR_NC} $1" | tee -a "$LOG_FILE"
}

validate_system() {
    log "\n=========================================="
    log "DEPLOYMENT VALIDATION"
    log "=========================================="
    
    local passed=0
    local failed=0
    local warnings=0
    
    # 1. Python Environment
    log "\n[1/8] Python Environment..."
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version)
        check_passed "Python available: $PYTHON_VERSION"
        ((passed++))
    else
        check_failed "Python3 not found"
        ((failed++))
    fi
    
    # 2. Required Directories
    log "\n[2/8] Directory Structure..."
    required_dirs=("astroquant/backend" "astroquant/frontend" "astroquant/config" "astroquant/execution")
    for dir in "${required_dirs[@]}"; do
        if [ -d "$REPO_ROOT/$dir" ]; then
            check_passed "Directory exists: $dir"
            ((passed++))
        else
            check_failed "Missing directory: $dir"
            ((failed++))
        fi
    done
    
    # 3. Database Files
    log "\n[3/8] Database Files..."
    if [ -f "$REPO_ROOT/prop_state.db" ]; then
        check_passed "Props database: prop_state.db"
        ((passed++))
    else
        check_warning "Props database not initialized (will create on first run)"
        ((warnings++))
    fi
    
    if [ -f "$REPO_ROOT/ai_trade_journal.db" ]; then
        check_passed "Journal database: ai_trade_journal.db"
        ((passed++))
    else
        check_warning "Journal database not initialized (will create on first run)"
        ((warnings++))
    fi
    
    # 4. Configuration Files
    log "\n[4/8] Configuration..."
    if [ -f "$REPO_ROOT/astroquant/config/production_config.py" ]; then
        check_passed "Production config present"
        ((passed++))
    else
        check_failed "Production config missing"
        ((failed++))
    fi
    
    # 5. Runtime Integration Files
    log "\n[5/8] Runtime Integration Files..."
    if [ -f "$REPO_ROOT/astroquant/backend/runtime.py" ]; then
        check_passed "runtime.py singleton provider present"
        ((passed++))
    else
        check_failed "runtime.py MISSING - integration incomplete"
        ((failed++))
    fi
    
    # 6. Key Backend Files
    log "\n[6/8] Backend Modules..."
    backend_files=("main.py" "router_status.py" "router_market.py" "router_spread_offset.py")
    for file in "${backend_files[@]}"; do
        if [ -f "$REPO_ROOT/astroquant/backend/$file" ]; then
            # Check if imports runtime.py where needed
            if grep -q "from astroquant.backend.runtime import" "$REPO_ROOT/astroquant/backend/$file" 2>/dev/null || [ "$file" = "main.py" ]; then
                check_passed "Backend module: $file (runtime-integrated)"
                ((passed++))
            else
                check_warning "Backend module: $file (exists, may need integration)"
                ((warnings++))
            fi
        else
            check_failed "Backend module missing: $file"
            ((failed++))
        fi
    done
    
    # 7. Playwright Integration
    log "\n[7/8] Playwright Integration..."
    if grep -q "def connect_to_broker" "$REPO_ROOT/astroquant/execution/playwright_engine.py" 2>/dev/null; then
        check_passed "Playwright connect_to_broker() implemented"
        ((passed++))
    else
        check_failed "Playwright connect_to_broker() NOT FOUND"
        ((failed++))
    fi
    
    # 8. Validation Scripts
    log "\n[8/8] Validation Scripts..."
    if [ -f "$REPO_ROOT/preflight_strict.sh" ] && [ -f "$REPO_ROOT/health_check.sh" ]; then
        check_passed "Validation scripts present (preflight_strict.sh, health_check.sh)"
        ((passed++))
    else
        check_failed "Validation scripts missing"
        ((failed++))
    fi
    
    # Summary
    log "\n=========================================="
    log "VALIDATION SUMMARY"
    log "=========================================="
    log "Passed:   $passed"
    log "Failed:   $failed"
    log "Warnings: $warnings"
    
    if [ $failed -eq 0 ]; then
        check_passed "VALIDATION PASSED - System ready for deployment"
        return 0
    else
        check_failed "VALIDATION FAILED - Fix issues before deployment"
        return 1
    fi
}

create_deployment_bundle() {
    log "\n=========================================="
    log "DEPLOYMENT BUNDLE CREATION"
    log "=========================================="
    
    BUNDLE_DIR="/tmp/astroquant_deployment_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BUNDLE_DIR"
    
    log "\nBundle directory: $BUNDLE_DIR"
    
    # Copy key files
    log "\nCopying backend files..."
    cp -r "$REPO_ROOT/astroquant/backend" "$BUNDLE_DIR/" 2>&1 | tee -a "$LOG_FILE"
    cp -r "$REPO_ROOT/astroquant/config" "$BUNDLE_DIR/" 2>&1 | tee -a "$LOG_FILE"
    cp -r "$REPO_ROOT/astroquant/execution" "$BUNDLE_DIR/" 2>&1 | tee -a "$LOG_FILE"
    cp -r "$REPO_ROOT/astroquant/engine" "$BUNDLE_DIR/" 2>&1 | tee -a "$LOG_FILE"
    
    log "Copying validation scripts..."
    cp "$REPO_ROOT/preflight_strict.sh" "$BUNDLE_DIR/" 2>&1 | tee -a "$LOG_FILE"
    cp "$REPO_ROOT/health_check.sh" "$BUNDLE_DIR/" 2>&1 | tee -a "$LOG_FILE"
    
    log "Copying requirements and README..."
    cp "$REPO_ROOT/requirements.txt" "$BUNDLE_DIR/" 2>&1 | tee -a "$LOG_FILE"
    cp "$REPO_ROOT/README.md" "$BUNDLE_DIR/" 2>&1 | tee -a "$LOG_FILE"
    cp "$REPO_ROOT/RUNTIME_INTEGRATION_COMPLETE.md" "$BUNDLE_DIR/DEPLOYMENT_NOTES.md" 2>&1 | tee -a "$LOG_FILE"
    
    # Create startup script
    cat > "$BUNDLE_DIR/start_backend.sh" << 'EOF'
#!/bin/bash
set -e
cd "$(dirname "$0")"
python -m uvicorn astroquant.backend.main:app \
  --host 0.0.0.0 --port 8000 \
  --workers 2 --timeout-graceful-shutdown 5
EOF
    chmod +x "$BUNDLE_DIR/start_backend.sh"
    
    # Create validation script
    cat > "$BUNDLE_DIR/validate_deployment.sh" << 'EOF'
#!/bin/bash
set -e
echo "========================================"
echo "DEPLOYMENT VALIDATION"
echo "========================================"
echo ""
echo "Backend connectivity..."
curl -s http://localhost:8000/health | jq . || echo "Backend not responding"
echo ""
echo "Running preflight checks..."
bash ./preflight_strict.sh http://localhost:8000
echo ""
echo "Running health checks..."
bash ./health_check.sh http://localhost:8000
echo ""
echo "========================================"
echo "Validation complete. Check output above."
echo "========================================"
EOF
    chmod +x "$BUNDLE_DIR/validate_deployment.sh"
    
    # Create tarball
    TARBALL="/tmp/astroquant_deployment_$(date +%Y%m%d_%H%M%S).tar.gz"
    log "\nCreating tarball: $TARBALL"
    tar -czf "$TARBALL" -C /tmp "$(basename $BUNDLE_DIR)" 2>&1 | tee -a "$LOG_FILE"
    
    check_passed "Deployment bundle created: $TARBALL"
    check_passed "Bundle directory: $BUNDLE_DIR"
    
    log "\nBundle contents:"
    tar -tzf "$TARBALL" | head -20
    
    # Create manifest
    MANIFEST="$BUNDLE_DIR/MANIFEST.txt"
    cat > "$MANIFEST" << EOF
ASTROQUANT DEPLOYMENT BUNDLE
Generated: $(date)

Contents:
- Backend FastAPI application (astroquant/backend/)
- Configuration (astroquant/config/)
- Execution engine (astroquant/execution/)
- Data processing engine (astroquant/engine/)
- Validation scripts (preflight_strict.sh, health_check.sh)
- Deployment notes (DEPLOYMENT_NOTES.md)
- Startup script (start_backend.sh)
- Validation helper (validate_deployment.sh)

Deployment Steps:
1. Extract bundle on target server
2. Install Python dependencies: pip install -r requirements.txt
3. Verify environment: bash validate_deployment.sh
4. Start backend: bash start_backend.sh
5. Monitor: tail -f backend.log

Configuration:
- Backend listens on 0.0.0.0:8000
- 2 uvicorn workers recommended
- Requires: Python 3.9+, Databento API key, Chrome/CDP for trading

Support:
- Check DEPLOYMENT_NOTES.md for known issues
- Review health_check.sh output for diagnostics
- Enable debug logging in config/production_config.py if needed
EOF
    
    log "\n$(cat $MANIFEST)"
    
    return 0
}

main() {
    local action="${1:-both}"
    
    echo "Logging to: $LOG_FILE"
    
    case "$action" in
        validate)
            validate_system
            ;;
        package)
            create_deployment_bundle
            ;;
        both)
            validate_system && create_deployment_bundle
            ;;
        *)
            echo "Usage: $0 [validate|package|both]"
            exit 1
            ;;
    esac
}

main "$@"
