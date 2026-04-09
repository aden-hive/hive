"""Tests for economic mode --node-budget CLI argument parsing."""

import argparse

from framework.runner import cli as runner_cli


def _make_parser() -> argparse.ArgumentParser:
    """Build a parser that includes the runner subcommands."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    runner_cli.register_commands(subparsers)
    return parser


class TestNodeBudgetArgParsing:
    """Verify the --node-budget flag is parsed correctly by the CLI."""

    def test_budget_integer_is_parsed(self):
        parser = _make_parser()
        args = parser.parse_args(["run", "my-agent", "--node-budget", "5"])
        assert args.node_budget == 5

    def test_budget_zero_is_parsed(self):
        """node_budget=0 is a valid value meaning 'block all paid calls'."""
        parser = _make_parser()
        args = parser.parse_args(["run", "my-agent", "--node-budget", "0"])
        assert args.node_budget == 0

    def test_budget_omitted_defaults_to_none(self):
        """When --node-budget is not passed, budget should be None (mode off)."""
        parser = _make_parser()
        args = parser.parse_args(["run", "my-agent"])
        assert getattr(args, "budget", None) is None

    def test_budget_large_value(self):
        parser = _make_parser()
        args = parser.parse_args(["run", "my-agent", "--node-budget", "1000"])
        assert args.node_budget == 1000
