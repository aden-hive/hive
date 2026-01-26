#!/bin/bash
# Hive Development Helper Script
# Simplifies common development tasks for the Aden Hive Framework

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Function to print section headers
print_header() {
    echo ""
    echo -e "${BLUE}=== $1 ===${NC}"
    echo ""
}

# Show help
show_help() {
    cat << 'EOF'
Hive Development Helper

Usage: ./dev-help.sh [command] [options]

Commands:
  setup              Setup development environment
  install            Install framework and tools packages
  test               Run test suite
  test:core          Run core framework tests
  test:coverage      Run tests with coverage report
  lint               Run code linting
  format             Format code with black
  clean              Clean build artifacts and cache
  validate           Validate all agents in exports/
  validate:agent     Validate specific agent (requires agent name)
  run:agent          Run specific agent in mock mode
  mcp:setup          Setup MCP server
  mcp:test           Test MCP server
  docs:check         Check documentation for broken links
  help               Show this help message

Examples:
  ./dev-help.sh setup                   # Complete setup
  ./dev-help.sh test                    # Run all tests
  ./dev-help.sh validate:agent my_agent # Validate my_agent
  ./dev-help.sh run:agent my_agent      # Run my_agent in mock mode
  ./dev-help.sh lint                    # Check code style

Environment:
  PYTHONPATH       Set automatically during tests
  MOCK_MODE        Set to 1 to run agents in mock mode
  LOG_LEVEL        Set to 'debug' for verbose logging

EOF
}

# Setup development environment
setup_dev() {
    print_header "Setting up Hive Development Environment"
    
    print_info "Step 1: Installing Python packages..."
    if [ -f "scripts/setup-python.sh" ]; then
        bash scripts/setup-python.sh
        print_success "Python packages installed"
    else
        print_error "setup-python.sh not found"
        return 1
    fi
    
    print_info "Step 2: Setting up MCP server..."
    if [ -f "core/setup_mcp.py" ]; then
        cd core
        python setup_mcp.py
        cd ..
        print_success "MCP server configured"
    else
        print_warning "MCP setup script not found"
    fi
    
    print_info "Step 3: Verifying installation..."
    python -c "import framework; import aden_tools; print('✓ All packages imported successfully')" && \
    print_success "Installation verified" || \
    print_error "Installation verification failed"
    
    print_success "Development environment ready!"
}

# Install packages
install_packages() {
    print_header "Installing Packages"
    
    print_info "Installing framework package..."
    cd core
    pip install -e .
    cd ..
    print_success "Framework installed"
    
    print_info "Installing aden_tools package..."
    cd tools
    pip install -e .
    cd ..
    print_success "aden_tools installed"
    
    print_success "All packages installed"
}

# Run tests
run_tests() {
    print_header "Running Test Suite"
    
    if ! command -v pytest &> /dev/null; then
        print_error "pytest not found. Installing..."
        pip install pytest pytest-asyncio pytest-cov
    fi
    
    export PYTHONPATH="core:exports:${PYTHONPATH}"
    
    print_info "Running tests..."
    python -m pytest core/tests/ -v --tb=short
    
    if [ $? -eq 0 ]; then
        print_success "All tests passed!"
    else
        print_error "Some tests failed"
        return 1
    fi
}

# Run tests with coverage
run_tests_coverage() {
    print_header "Running Tests with Coverage"
    
    if ! command -v pytest &> /dev/null; then
        print_error "pytest not found. Installing..."
        pip install pytest pytest-asyncio pytest-cov
    fi
    
    export PYTHONPATH="core:exports:${PYTHONPATH}"
    
    print_info "Running tests with coverage..."
    python -m pytest core/tests/ \
        --cov=framework \
        --cov-report=html \
        --cov-report=term-missing \
        -v
    
    if [ $? -eq 0 ]; then
        print_success "Coverage report generated in htmlcov/index.html"
    else
        print_error "Coverage analysis failed"
        return 1
    fi
}

# Run core framework tests only
run_core_tests() {
    print_header "Running Core Framework Tests"
    
    export PYTHONPATH="core:exports:${PYTHONPATH}"
    
    print_info "Running core tests..."
    python -m pytest core/tests/test_*.py -v --tb=short
    
    if [ $? -eq 0 ]; then
        print_success "Core tests passed!"
    else
        print_error "Core tests failed"
        return 1
    fi
}

# Lint code
lint_code() {
    print_header "Linting Code"
    
    if ! command -v pylint &> /dev/null; then
        print_warning "pylint not installed. Installing..."
        pip install pylint
    fi
    
    print_info "Checking code style..."
    python -m pylint core/framework/**/*.py --disable=all --enable=E,F 2>/dev/null || true
    
    print_success "Lint check complete"
}

# Format code
format_code() {
    print_header "Formatting Code"
    
    if ! command -v black &> /dev/null; then
        print_warning "black not installed. Installing..."
        pip install black
    fi
    
    print_info "Formatting code..."
    python -m black core/framework --line-length=100
    python -m black tools/src/aden_tools --line-length=100
    
    print_success "Code formatted"
}

# Clean artifacts
clean_artifacts() {
    print_header "Cleaning Build Artifacts"
    
    print_info "Removing cache directories..."
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name *.egg-info -exec rm -rf {} + 2>/dev/null || true
    
    print_info "Removing build directories..."
    rm -rf core/build core/dist tools/build tools/dist 2>/dev/null || true
    
    print_success "Artifacts cleaned"
}

# Validate agents
validate_agents() {
    print_header "Validating Agents"
    
    export PYTHONPATH="core:exports:${PYTHONPATH}"
    
    if [ ! -d "exports" ]; then
        print_warning "No exports directory found"
        return 0
    fi
    
    agent_count=0
    for agent_dir in exports/*/; do
        if [ -d "$agent_dir" ]; then
            agent_name=$(basename "$agent_dir")
            print_info "Validating agent: $agent_name"
            
            python -m "$agent_name" validate 2>/dev/null && \
            print_success "  ✓ $agent_name validated" || \
            print_error "  ✗ $agent_name validation failed"
            
            agent_count=$((agent_count + 1))
        fi
    done
    
    if [ $agent_count -eq 0 ]; then
        print_warning "No agents found in exports/"
    else
        print_success "Validated $agent_count agent(s)"
    fi
}

# Validate specific agent
validate_agent() {
    if [ -z "$1" ]; then
        print_error "Agent name required. Usage: ./dev-help.sh validate:agent <agent_name>"
        return 1
    fi
    
    print_header "Validating Agent: $1"
    
    export PYTHONPATH="core:exports:${PYTHONPATH}"
    
    if [ ! -d "exports/$1" ]; then
        print_error "Agent 'exports/$1' not found"
        return 1
    fi
    
    python -m "$1" validate
    
    if [ $? -eq 0 ]; then
        print_success "Agent '$1' is valid"
    else
        print_error "Agent '$1' validation failed"
        return 1
    fi
}

# Run agent in mock mode
run_agent() {
    if [ -z "$1" ]; then
        print_error "Agent name required. Usage: ./dev-help.sh run:agent <agent_name> [input]"
        return 1
    fi
    
    print_header "Running Agent: $1"
    
    export PYTHONPATH="core:exports:${PYTHONPATH}"
    
    if [ ! -d "exports/$1" ]; then
        print_error "Agent 'exports/$1' not found"
        return 1
    fi
    
    # Use provided input or default
    input='{"task": "test"}'
    if [ -n "$2" ]; then
        input="$2"
    fi
    
    print_info "Running in mock mode..."
    python -m "$1" run --mock --input "$input"
}

# Setup MCP
setup_mcp() {
    print_header "Setting up MCP Server"
    
    cd core
    python setup_mcp.py
    cd ..
    
    if [ -f "core/.mcp.json" ]; then
        print_success "MCP server configured"
        print_info "Configuration file: core/.mcp.json"
    else
        print_error "MCP configuration failed"
        return 1
    fi
}

# Test MCP
test_mcp() {
    print_header "Testing MCP Server"
    
    export PYTHONPATH="core:exports:${PYTHONPATH}"
    
    print_info "Importing MCP server module..."
    python -c "from framework.mcp.agent_builder_server import MCP" && \
    print_success "MCP server imports successfully" || \
    (print_error "MCP server import failed"; return 1)
}

# Main command handler
main() {
    if [ $# -eq 0 ]; then
        show_help
        return 0
    fi
    
    case "$1" in
        setup)
            setup_dev
            ;;
        install)
            install_packages
            ;;
        test)
            run_tests
            ;;
        test:core)
            run_core_tests
            ;;
        test:coverage)
            run_tests_coverage
            ;;
        lint)
            lint_code
            ;;
        format)
            format_code
            ;;
        clean)
            clean_artifacts
            ;;
        validate)
            validate_agents
            ;;
        validate:agent)
            validate_agent "$2"
            ;;
        run:agent)
            run_agent "$2" "$3"
            ;;
        mcp:setup)
            setup_mcp
            ;;
        mcp:test)
            test_mcp
            ;;
        docs:check)
            print_info "Documentation link checking coming soon"
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            echo ""
            show_help
            return 1
            ;;
    esac
}

# Run main function
main "$@"
