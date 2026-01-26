@echo off
REM Hive Development Helper Script (Windows)
REM Simplifies common development tasks for the Aden Hive Framework

setlocal enabledelayedexpansion

REM Color codes (using findstr hack)
set "RED="
set "GREEN="
set "YELLOW="
set "BLUE="
set "NC="

REM Function to show help
if "%1"=="" (
    call :show_help
    exit /b 0
)

if "%1"=="help" (
    call :show_help
    exit /b 0
)

if "%1"=="--help" (
    call :show_help
    exit /b 0
)

if "%1"=="-h" (
    call :show_help
    exit /b 0
)

REM Route commands
if "%1"=="setup" (
    call :setup_dev
    exit /b !errorlevel!
)

if "%1"=="install" (
    call :install_packages
    exit /b !errorlevel!
)

if "%1"=="test" (
    call :run_tests
    exit /b !errorlevel!
)

if "%1"=="test:core" (
    call :run_core_tests
    exit /b !errorlevel!
)

if "%1"=="test:coverage" (
    call :run_tests_coverage
    exit /b !errorlevel!
)

if "%1"=="lint" (
    call :lint_code
    exit /b !errorlevel!
)

if "%1"=="format" (
    call :format_code
    exit /b !errorlevel!
)

if "%1"=="clean" (
    call :clean_artifacts
    exit /b !errorlevel!
)

if "%1"=="validate" (
    call :validate_agents
    exit /b !errorlevel!
)

if "%1"=="validate:agent" (
    call :validate_agent %2
    exit /b !errorlevel!
)

if "%1"=="run:agent" (
    call :run_agent %2 %3
    exit /b !errorlevel!
)

if "%1"=="mcp:setup" (
    call :setup_mcp
    exit /b !errorlevel!
)

if "%1"=="mcp:test" (
    call :test_mcp
    exit /b !errorlevel!
)

echo Unknown command: %1
call :show_help
exit /b 1

REM ===== Function Definitions =====

:show_help
echo Hive Development Helper (Windows)
echo.
echo Usage: dev-help.bat [command] [options]
echo.
echo Commands:
echo   setup              Setup development environment
echo   install            Install framework and tools packages
echo   test               Run test suite
echo   test:core          Run core framework tests
echo   test:coverage      Run tests with coverage report
echo   lint               Run code linting
echo   format             Format code with black
echo   clean              Clean build artifacts and cache
echo   validate           Validate all agents in exports/
echo   validate:agent     Validate specific agent (requires agent name)
echo   run:agent          Run specific agent in mock mode
echo   mcp:setup          Setup MCP server
echo   mcp:test           Test MCP server
echo   help               Show this help message
echo.
echo Examples:
echo   dev-help.bat setup                   (Complete setup)
echo   dev-help.bat test                    (Run all tests)
echo   dev-help.bat validate:agent my_agent (Validate my_agent)
echo   dev-help.bat run:agent my_agent      (Run my_agent in mock mode)
exit /b 0

:setup_dev
echo === Setting up Hive Development Environment ===
echo.

echo Installing Python packages...
if exist scripts\setup-python.sh (
    powershell -Command "& 'scripts\setup-python.sh'"
    echo [OK] Python packages installed
) else (
    echo [ERROR] setup-python.sh not found
    exit /b 1
)

echo.
echo Setting up MCP server...
if exist core\setup_mcp.py (
    cd core
    python setup_mcp.py
    cd ..
    echo [OK] MCP server configured
) else (
    echo [WARNING] MCP setup script not found
)

echo.
echo Verifying installation...
python -c "import framework; import aden_tools; print('OK: All packages imported successfully')"
if !errorlevel! equ 0 (
    echo [OK] Installation verified
) else (
    echo [ERROR] Installation verification failed
    exit /b 1
)

echo.
echo [OK] Development environment ready!
exit /b 0

:install_packages
echo === Installing Packages ===
echo.

echo Installing framework package...
cd core
pip install -e .
cd ..
if !errorlevel! equ 0 (
    echo [OK] Framework installed
) else (
    echo [ERROR] Framework installation failed
    exit /b 1
)

echo.
echo Installing aden_tools package...
cd tools
pip install -e .
cd ..
if !errorlevel! equ 0 (
    echo [OK] aden_tools installed
) else (
    echo [ERROR] aden_tools installation failed
    exit /b 1
)

echo.
echo [OK] All packages installed
exit /b 0

:run_tests
echo === Running Test Suite ===
echo.

where pytest >nul 2>nul
if !errorlevel! neq 0 (
    echo Installing pytest...
    pip install pytest pytest-asyncio pytest-cov
)

set PYTHONPATH=core;exports;%PYTHONPATH%

echo Running tests...
python -m pytest core/tests/ -v --tb=short

if !errorlevel! equ 0 (
    echo [OK] All tests passed!
) else (
    echo [ERROR] Some tests failed
    exit /b 1
)
exit /b 0

:run_tests_coverage
echo === Running Tests with Coverage ===
echo.

where pytest >nul 2>nul
if !errorlevel! neq 0 (
    echo Installing pytest and coverage...
    pip install pytest pytest-asyncio pytest-cov
)

set PYTHONPATH=core;exports;%PYTHONPATH%

echo Running tests with coverage...
python -m pytest core/tests/ ^
    --cov=framework ^
    --cov-report=html ^
    --cov-report=term-missing ^
    -v

if !errorlevel! equ 0 (
    echo [OK] Coverage report generated in htmlcov/index.html
) else (
    echo [ERROR] Coverage analysis failed
    exit /b 1
)
exit /b 0

:run_core_tests
echo === Running Core Framework Tests ===
echo.

set PYTHONPATH=core;exports;%PYTHONPATH%

echo Running core tests...
python -m pytest core/tests/test_*.py -v --tb=short

if !errorlevel! equ 0 (
    echo [OK] Core tests passed!
) else (
    echo [ERROR] Core tests failed
    exit /b 1
)
exit /b 0

:lint_code
echo === Linting Code ===
echo.

where pylint >nul 2>nul
if !errorlevel! neq 0 (
    echo Installing pylint...
    pip install pylint
)

echo Checking code style...
python -m pylint core/framework --disable=all --enable=E,F

echo [OK] Lint check complete
exit /b 0

:format_code
echo === Formatting Code ===
echo.

where black >nul 2>nul
if !errorlevel! neq 0 (
    echo Installing black...
    pip install black
)

echo Formatting code...
python -m black core/framework --line-length=100
python -m black tools/src/aden_tools --line-length=100

echo [OK] Code formatted
exit /b 0

:clean_artifacts
echo === Cleaning Build Artifacts ===
echo.

echo Removing cache directories...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
for /d /r . %%d in (.pytest_cache) do @if exist "%%d" rd /s /q "%%d" 2>nul
for /d /r . %%d in (.mypy_cache) do @if exist "%%d" rd /s /q "%%d" 2>nul

echo Removing build directories...
if exist core\build rd /s /q core\build 2>nul
if exist core\dist rd /s /q core\dist 2>nul
if exist tools\build rd /s /q tools\build 2>nul
if exist tools\dist rd /s /q tools\dist 2>nul

echo [OK] Artifacts cleaned
exit /b 0

:validate_agents
echo === Validating Agents ===
echo.

set PYTHONPATH=core;exports;%PYTHONPATH%

if not exist exports (
    echo [WARNING] No exports directory found
    exit /b 0
)

setlocal enabledelayedexpansion
set agent_count=0

for /d %%A in (exports\*) do (
    set agent_name=%%~nxA
    echo Validating agent: !agent_name!
    python -m !agent_name! validate >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [OK] !agent_name! validated
    ) else (
        echo   [ERROR] !agent_name! validation failed
    )
    set /a agent_count+=1
)

echo [OK] Validated !agent_count! agent(s)
exit /b 0

:validate_agent
if "%~1"=="" (
    echo [ERROR] Agent name required. Usage: dev-help.bat validate:agent ^<agent_name^>
    exit /b 1
)

echo === Validating Agent: %1 ===
echo.

set PYTHONPATH=core;exports;%PYTHONPATH%

if not exist "exports\%1" (
    echo [ERROR] Agent 'exports\%1' not found
    exit /b 1
)

python -m %1 validate

if !errorlevel! equ 0 (
    echo [OK] Agent '%1' is valid
) else (
    echo [ERROR] Agent '%1' validation failed
    exit /b 1
)
exit /b 0

:run_agent
if "%~1"=="" (
    echo [ERROR] Agent name required. Usage: dev-help.bat run:agent ^<agent_name^> [input]
    exit /b 1
)

echo === Running Agent: %1 ===
echo.

set PYTHONPATH=core;exports;%PYTHONPATH%

if not exist "exports\%1" (
    echo [ERROR] Agent 'exports\%1' not found
    exit /b 1
)

set input={"task": "test"}
if not "%~2"=="" (
    set input=%2
)

echo Running in mock mode...
python -m %1 run --mock --input "!input!"
exit /b !errorlevel!

:setup_mcp
echo === Setting up MCP Server ===
echo.

cd core
python setup_mcp.py
cd ..

if exist core\.mcp.json (
    echo [OK] MCP server configured
    echo Configuration file: core\.mcp.json
) else (
    echo [ERROR] MCP configuration failed
    exit /b 1
)
exit /b 0

:test_mcp
echo === Testing MCP Server ===
echo.

set PYTHONPATH=core;exports;%PYTHONPATH%

echo Importing MCP server module...
python -c "from framework.mcp.agent_builder_server import MCP"

if !errorlevel! equ 0 (
    echo [OK] MCP server imports successfully
) else (
    echo [ERROR] MCP server import failed
    exit /b 1
)
exit /b 0
