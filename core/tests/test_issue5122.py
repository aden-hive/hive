from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))

from framework.runner.cli import cmd_run
from framework.runner.runner import ValidationResult

class _FakeArgs:
    def __init__(self, **kw):
        self.agent_path = kw.pop("agent_path", Path("dummy"))
        self.interactive = kw.pop("interactive", False)
        self.quiet = kw.pop("quiet", True)
        self.input = kw.pop("input", "")
        self.input_file = kw.pop("input_file", None)
        self.output = kw.pop("output", None)
        self.model = kw.pop("model", None)
        self.skip_credential_validation = True
        for k, v in kw.items():
            setattr(self, k, v)

def _runner(validation, run_result_success=True):
    r = MagicMock()
    r.validate.return_value = validation
    r.cleanup = MagicMock()
    r.run = AsyncMock(return_value=MagicMock(success=run_result_success))
    return r

def test_validation():
    # 1. Validation error
    val_bad = ValidationResult(valid=False, errors=["err"], missing_tools=[], warnings=[], missing_credentials=[])
    run_bad = _runner(val_bad)
    with patch("framework.runner.runner.AgentRunner.load", return_value=run_bad):
        assert cmd_run(_FakeArgs()) == 1
    
    # 2. Missing tools
    val_tools = ValidationResult(valid=True, errors=[], missing_tools=["x"], warnings=[], missing_credentials=[])
    run_tools = _runner(val_tools)
    with patch("framework.runner.runner.AgentRunner.load", return_value=run_tools):
        assert cmd_run(_FakeArgs()) == 1
        
    # 3. Valid agent
    val_good = ValidationResult(valid=True, errors=[], missing_tools=[], warnings=[], missing_credentials=[])
    run_good = _runner(val_good)
    with patch("framework.runner.runner.AgentRunner.load", return_value=run_good):
        with patch("sys.stdin.isatty", return_value=False):
            assert cmd_run(_FakeArgs()) == 0
    
    print("ALL RIGOROUS TESTS PASSED")

if __name__ == "__main__":
    test_validation()
