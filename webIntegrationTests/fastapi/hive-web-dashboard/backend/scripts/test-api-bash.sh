#!/bin/bash

# Manual API Testing Script for Hive Dashboard
# This script allows testing the agent API endpoints directly without the web UI
# Usage: bash test-api-bash.sh [command] [options]

set -e

# Configuration
BACKEND_URL="http://localhost:5000"
HIVE_DIR="../../../hive"
PYTHON_CMD="python"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Test health endpoint
test_health() {
    log_info "Testing health endpoint..."
    
    if response=$(curl -s "${BACKEND_URL}/api/health"); then
        log_success "Health check response:"
        echo "$response" | python -m json.tool || echo "$response"
    else
        log_error "Failed to reach backend at ${BACKEND_URL}"
        return 1
    fi
}

# Test hive status endpoint
test_hive_status() {
    log_info "Testing /api/hive/status endpoint..."
    
    if response=$(curl -s "${BACKEND_URL}/api/hive/status"); then
        log_success "Hive status response:"
        echo "$response" | python -m json.tool || echo "$response"
    else
        log_error "Failed to reach /api/hive/status"
        return 1
    fi
}

# List available agents
list_agents() {
    log_info "Listing available agents..."
    
    if response=$(curl -s "${BACKEND_URL}/api/hive/agents"); then
        log_success "Agents response:"
        echo "$response" | python -m json.tool || echo "$response"
    else
        log_error "Failed to list agents"
        return 1
    fi
}

# Run agent directly via Python (bypass web)
run_agent_direct() {
    local input="$1"
    
    if [ -z "$input" ]; then
        log_error "Please provide input as argument: run_agent_direct 'your input'"
        return 1
    fi
    
    log_info "Running agent directly via Python..."
    log_info "Input: '$input'"
    log_info "Working directory: $HIVE_DIR"
    
    cd "$HIVE_DIR"
    if $PYTHON_CMD -m framework run customer_service_agent --input "$input"; then
        log_success "Agent execution completed"
    else
        log_error "Agent execution failed"
        return 1
    fi
    cd - > /dev/null
}

# Run agent via API endpoint
run_agent_api() {
    local input="$1"
    
    if [ -z "$input" ]; then
        log_error "Please provide input as argument: run_agent_api 'your input'"
        return 1
    fi
    
    log_info "Running agent via API endpoint..."
    log_info "Input: '$input'"
    
    # Create JSON payload
    local payload=$(cat <<EOF
{
  "input": "$input"
}
EOF
)
    
    log_info "Payload: $payload"
    
    if response=$(curl -s -X POST "${BACKEND_URL}/api/hive/run" \
        -H "Content-Type: application/json" \
        -d "$payload"); then
        
        log_success "Agent API response:"
        echo "$response" | python -m json.tool || echo "$response"
    else
        log_error "Failed to run agent via API"
        return 1
    fi
}

# Check agent execution state
check_state() {
    log_info "Checking agent execution state..."
    
    if response=$(curl -s "${BACKEND_URL}/api/hive/state"); then
        log_success "Execution state:"
        echo "$response" | python -m json.tool || echo "$response"
    else
        log_error "Failed to check state"
        return 1
    fi
}

# Get execution history
get_history() {
    local limit="${1:-10}"
    log_info "Getting execution history (limit: $limit)..."
    
    if response=$(curl -s "${BACKEND_URL}/api/hive/history?limit=$limit"); then
        log_success "Execution history:"
        echo "$response" | python -m json.tool || echo "$response"
    else
        log_error "Failed to get history"
        return 1
    fi
}

# Run all tests
run_all_tests() {
    log_info "Running all API tests..."
    echo ""
    
    log_warn "Test 1: Health Check"
    test_health || true
    echo ""
    
    log_warn "Test 2: Hive Status"
    test_hive_status || true
    echo ""
    
    log_warn "Test 3: List Agents"
    list_agents || true
    echo ""
    
    log_warn "Test 4: Check State"
    check_state || true
    echo ""
    
    log_warn "Test 5: Get History"
    get_history 5 || true
    echo ""
    
    log_success "All tests completed!"
}

# Display usage
usage() {
    cat <<EOF
${BLUE}Hive Dashboard API Testing Script${NC}

${YELLOW}Usage:${NC}
  bash test-api-bash.sh [command] [options]

${YELLOW}Commands:${NC}
  health                      Test backend health endpoint
  hive-status                 Get Hive framework status
  agents                      List available agents
  state                       Check current agent execution state
  history [limit]             Get execution history (default: 10)
  
  run-api "input"            Run agent via API endpoint
  run-direct "input"         Run agent directly via Python
  
  test-all                    Run all test endpoints

${YELLOW}Examples:${NC}
  bash test-api-bash.sh health
  bash test-api-bash.sh run-api "I forgot my password"
  bash test-api-bash.sh run-direct "How do I reset my account?"
  bash test-api-bash.sh history 20

${YELLOW}Environment Variables:${NC}
  BACKEND_URL                 Backend server URL (default: http://localhost:5000)
  PYTHON_CMD                  Python executable (default: python)

EOF
}

# Main command routing
main() {
    if [ $# -eq 0 ]; then
        usage
        exit 0
    fi
    
    case "$1" in
        health)
            test_health
            ;;
        hive-status)
            test_hive_status
            ;;
        agents|list-agents)
            list_agents
            ;;
        state|check-state)
            check_state
            ;;
        history)
            get_history "$2"
            ;;
        run-api)
            run_agent_api "$2"
            ;;
        run-direct)
            run_agent_direct "$2"
            ;;
        test-all)
            run_all_tests
            ;;
        --help|-h|help)
            usage
            ;;
        *)
            log_error "Unknown command: $1"
            echo ""
            usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
