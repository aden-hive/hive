
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))
from framework.runner.cli import cmd_run

def test_run_validates_agent():
    print("[TEST] Running validation check on cmd_run...")
    from pathlib import Path
    import subprocess
    agent_dir = Path(__file__).parent / "test_agents" / "invalid_agent"
    result = subprocess.run(
        [sys.executable, "-m", "core.framework.runner.cli", "run", str(agent_dir)],
        capture_output=True, text=True, cwd=Path(__file__).parent
    )
    if result.returncode == 1 and ("ERROR" in result.stderr or "Error" in result.stdout or "valid" in result.stdout):
        print(f"[PASS] Run aborted with exit code {result.returncode}. Output: {result.stdout[:200]}")
    else:
        print(f"[FAIL] Expected exit code 1. Got: {result.returncode}")
        print(f"Stdout: {result.stdout[:500]}")
        print(f"Stderr: {result.stderr[:500]}")
        sys.exit(1)

if __name__ == "__main__":
    test_run_validates_agent()
