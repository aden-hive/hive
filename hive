#!/usr/bin/env bash
#
# Wrapper script for the Hive CLI.
# Uses uv to run the hive command in the project's virtual environment.
#
# Usage:
#   ./hive tui           - Launch interactive agent dashboard
#   ./hive run <agent>   - Run an agent
#   ./hive --help        - Show all commands
#

set -e

# Resolve symlinks to find the real script location
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"
    SOURCE="$(readlink "$SOURCE")"
    # Handle relative symlinks
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"

# Verify user is running from the hive project directory
USER_CWD="$(pwd)"
if [ "$USER_CWD" != "$SCRIPT_DIR" ]; then
    echo "Error: hive must be run from the project directory." >&2
    echo "" >&2
    echo "  Current directory: $USER_CWD" >&2
    echo "  Expected directory: $SCRIPT_DIR" >&2
    echo "" >&2
    echo "Run: cd $SCRIPT_DIR" >&2
    exit 1
fi

cd "$SCRIPT_DIR"

# Verify this is a valid Hive project directory
if [ ! -f "$SCRIPT_DIR/pyproject.toml" ] || [ ! -d "$SCRIPT_DIR/core" ]; then
    echo "Error: Not a valid Hive project directory: $SCRIPT_DIR" >&2
    echo "" >&2
    echo "The hive CLI must be run from a Hive project root." >&2
    echo "Expected files: pyproject.toml, core/" >&2
    exit 1
fi

if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "Error: Virtual environment not found." >&2
    echo "" >&2
    echo "Run ./quickstart.sh first to set up the project." >&2
    exit 1
fi

# Ensure uv is in PATH (common install locations)
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Run ./quickstart.sh first." >&2
    exit 1
fi

exec uv run hive "$@"
