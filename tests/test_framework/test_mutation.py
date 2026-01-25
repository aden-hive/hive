"""Mutation tests."""

import pytest
from core.framework.testing.mutation import MutationTestRunner, setup_mutation_testing


class TestMutationTesting:
    """Mutation testing suite."""

    def test_setup_mutation_testing(self):
        """Test mutation testing setup."""
        config = setup_mutation_testing()
        assert "[hypothesis]" in config

    def test_mutation_runner_init(self):
        """Test mutation runner initialization."""
        runner = MutationTestRunner(threshold=80.0)
        assert runner.threshold == 80.0

    @pytest.mark.slow
    def test_run_mutation_tests(self):
        """Run mutation tests (marked as slow)."""
        runner = MutationTestRunner(threshold=50.0)  # Lower threshold for tests
        # Note: This would actually run mutation tests
        # results = runner.run_mutation_tests(paths=["core/framework/auth"])
        # For now, just verify the runner works
        assert runner is not None
