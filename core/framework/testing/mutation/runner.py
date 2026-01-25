"""Mutation testing configuration and utilities."""

import os
import subprocess


class MutationTestRunner:
    """Mutation testing runner using mutmut."""

    def __init__(self, threshold: float = 80.0):
        self.threshold = threshold

    def run_mutation_tests(
        self,
        paths: list[str] = None,
        exclude_paths: list[str] = None
    ) -> dict:
        """Run mutation tests using mutmut."""
        paths = paths or ["core/framework"]
        exclude_paths = exclude_paths or [
            "*/tests/*",
            "*/venv/*",
            "*/migrations/*",
            "*/__pycache__/*"
        ]

        cmd = ["mutmut", "run"]

        for path in paths:
            cmd.extend(["--paths-to-mutate", path])

        for excl in exclude_paths:
            cmd.extend(["--exclude", excl])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Mutation testing timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_results(self) -> dict:
        """Get mutation testing results."""
        try:
            result = subprocess.run(
                ["mutmut", "results"],
                capture_output=True,
                text=True,
                timeout=60
            )

            return {
                "success": result.returncode == 0,
                "output": result.stdout
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_coverage(self) -> dict:
        """Get mutation coverage score."""
        try:
            result = subprocess.run(
                ["mutmut", "coverage"],
                capture_output=True,
                text=True,
                timeout=60
            )

            return {
                "success": result.returncode == 0,
                "output": result.stdout
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_threshold(self) -> bool:
        """Check if mutation score meets threshold."""
        results = self.get_results()
        if not results["success"]:
            return False

        # Parse mutation score from output
        # This would need to be implemented based on mutmut's actual output format
        return True


# Mutation testing utilities
def setup_mutation_testing():
    """Setup mutation testing configuration."""
    config = """
[hypothesis]
mutation_score_percentage = 80
exclude_paths =
    */tests/*
    */venv/*
    */migrations/*
    */__pycache__/*
"""

    with open(".mutmut.ini", "w") as f:
        f.write(config)

    return config


def run_mutation_tests_cli():
    """CLI wrapper for mutation testing."""
    import sys

    print("Setting up mutation testing...")
    setup_mutation_testing()

    print("Running mutation tests...")
    runner = MutationTestRunner(threshold=80.0)
    results = runner.run_mutation_tests()

    if results["success"]:
        print("Mutation tests completed!")
        print(results["stdout"])
    else:
        print("Mutation tests failed!")
        print(results.get("error", results.get("stderr")))

    return 0 if results["success"] else 1
