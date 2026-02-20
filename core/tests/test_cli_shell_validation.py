import sys
from argparse import Namespace

import framework.runner as runner_pkg
import framework.runner.cli as cli


class FakeRunner:
    def validate(self):
        from framework.runner import ValidationResult

        return ValidationResult(valid=False, errors=["Entry node '' not found"])

    def cleanup(self):
        pass


def test_shell_aborts_on_invalid_agent(monkeypatch, capsys, tmp_path):
    # Patch AgentRunner.load to return a fake invalid runner
    monkeypatch.setattr(
        "framework.runner.AgentRunner.load", lambda *a, **k: FakeRunner()
    )

    # Ensure no interactive prompts (stdin is not a TTY)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    args = Namespace(agent_path=str(tmp_path), agents_dir="exports", multi=False, no_approve=True)

    ret = cli.cmd_shell(args)

    captured = capsys.readouterr()
    assert ret == 1
    assert "Agent has validation errors" in captured.err
    assert "Entry node" in captured.err
