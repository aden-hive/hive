"""
Interactive CLI for reviewing and approving generated tests.

LLM-generated tests are NEVER created without user approval.
This CLI provides the interactive approval workflow.
"""

import json
import os
import subprocess
import tempfile
from collections.abc import Callable

from framework.testing.approval_types import (
    ApprovalAction,
    ApprovalRequest,
    ApprovalResult,
    BatchApprovalResult,
)
from framework.testing.test_case import Test
from framework.testing.test_storage import TestStorage


def interactive_approval(
    tests: list[Test],
    storage: TestStorage,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[ApprovalResult]:
    """
    Interactive CLI flow for reviewing generated tests.

    Displays each test and allows user to:
    - [a]pprove: Accept as-is
    - [r]eject: Decline with reason
    - [e]dit: Modify before accepting
    - [s]kip: Leave pending (decide later)

    Args:
        tests: List of pending tests to review
        storage: TestStorage for saving decisions
        on_progress: Optional callback(current, total) for progress tracking

    Returns:
        List of ApprovalResult for each processed test
    """
    results = []
    total = len(tests)

    for i, test in enumerate(tests, 1):
        if on_progress:
            on_progress(i, total)

        # Display test
        _display_test(test, i, total)

        # Get user action
        action = _get_user_action()

        # Process action
        result = _process_action(test, action, storage)
        results.append(result)

        print()  # Blank line between tests

    return results


def batch_approval(
    goal_id: str,
    requests: list[ApprovalRequest],
    storage: TestStorage,
) -> BatchApprovalResult:
    """
    Process multiple approval requests at once.

    Used by MCP interface for programmatic approval.

    Args:
        goal_id: Goal ID for the tests
        requests: List of approval requests
        storage: TestStorage for saving decisions

    Returns:
        BatchApprovalResult with counts and individual results
    """
    results = []
    counts = {
        "approved": 0,
        "modified": 0,
        "rejected": 0,
        "skipped": 0,
        "errors": 0,
    }

    for req in requests:
        # Validate request
        valid, error = req.validate_action()
        if not valid:
            results.append(
                ApprovalResult.error_result(req.test_id, req.action, error or "Invalid request")
            )
            counts["errors"] += 1
            continue

        # Load test
        test = storage.load_test(goal_id, req.test_id)
        if not test:
            results.append(
                ApprovalResult.error_result(
                    req.test_id, req.action, f"Test {req.test_id} not found"
                )
            )
            counts["errors"] += 1
            continue

        # Apply action
        try:
            if req.action == ApprovalAction.APPROVE:
                test.approve(req.approved_by)
                counts["approved"] += 1
            elif req.action == ApprovalAction.MODIFY:
                test.modify(req.modified_code or test.test_code, req.approved_by)
                counts["modified"] += 1
            elif req.action == ApprovalAction.REJECT:
                test.reject(req.reason or "No reason provided")
                counts["rejected"] += 1
            elif req.action == ApprovalAction.SKIP:
                counts["skipped"] += 1

            # Save if not skipped
            if req.action != ApprovalAction.SKIP:
                storage.update_test(test)

            results.append(
                ApprovalResult.success_result(
                    req.test_id, req.action, f"Test {req.action.value}d successfully"
                )
            )

        except Exception as e:
            results.append(ApprovalResult.error_result(req.test_id, req.action, str(e)))
            counts["errors"] += 1

    return BatchApprovalResult(
        goal_id=goal_id,
        total=len(requests),
        approved=counts["approved"],
        modified=counts["modified"],
        rejected=counts["rejected"],
        skipped=counts["skipped"],
        errors=counts["errors"],
        results=results,
    )


def _display_test(test: Test, index: int, total: int) -> None:
    """Display a test for review."""
    separator = "=" * 60

    print(f"\n{separator}")
    print(f"[{index}/{total}] {test.test_name}")
    print(f"Type: {test.test_type.value}")
    print(f"Criteria: {test.parent_criteria_id}")
    print(f"Confidence: {test.llm_confidence * 100:.0f}%")
    print(separator)

    print(f"\nDescription: {test.description}")

    if test.input:
        print("\nInput:")
        print(json.dumps(test.input, indent=2))

    if test.expected_output:
        print("\nExpected Output:")
        print(json.dumps(test.expected_output, indent=2))

    print("\nTest Code:")
    print("-" * 40)
    print(test.test_code)
    print("-" * 40)

    print("\n[a]pprove  [r]eject  [e]dit  [s]kip")


def _get_user_action() -> ApprovalAction:
    """Get user's choice for action."""
    while True:
        choice = input("Your choice: ").strip().lower()

        if choice == "a":
            return ApprovalAction.APPROVE
        elif choice == "r":
            return ApprovalAction.REJECT
        elif choice == "e":
            return ApprovalAction.MODIFY
        elif choice == "s":
            return ApprovalAction.SKIP
        else:
            print("Invalid choice. Please enter a, r, e, or s.")


def _process_action(
    test: Test,
    action: ApprovalAction,
    storage: TestStorage,
) -> ApprovalResult:
    """Process user's action on a test."""
    try:
        if action == ApprovalAction.APPROVE:
            test.approve()
            storage.update_test(test)
            print("✓ Approved")
            return ApprovalResult.success_result(test.id, action, "Approved")

        elif action == ApprovalAction.REJECT:
            reason = input("Rejection reason: ").strip()
            if not reason:
                reason = "No reason provided"
            test.reject(reason)
            storage.update_test(test)
            print(f"✗ Rejected: {reason}")
            return ApprovalResult.success_result(test.id, action, f"Rejected: {reason}")

        elif action == ApprovalAction.MODIFY:
            edited_code = _edit_test_code(test.test_code)
            if edited_code != test.test_code:
                test.modify(edited_code)
                storage.update_test(test)
                print("✓ Modified and approved")
                return ApprovalResult.success_result(test.id, action, "Modified and approved")
            else:
                # No changes made, treat as approve
                test.approve()
                storage.update_test(test)
                print("✓ Approved (no modifications)")
                return ApprovalResult.success_result(
                    test.id, ApprovalAction.APPROVE, "No modifications made"
                )

        elif action == ApprovalAction.SKIP:
            print("⏭ Skipped (remains pending)")
            return ApprovalResult.success_result(test.id, action, "Skipped")

        else:
            return ApprovalResult.error_result(test.id, action, f"Unknown action: {action}")

    except Exception as e:
        return ApprovalResult.error_result(test.id, action, str(e))


def _edit_test_code(code: str) -> str:
    """
    Open test code in user's editor for modification.

    Uses $EDITOR environment variable, falls back to vim/nano.
    """
    editor = os.environ.get("EDITOR", "vim")

    # Try to find an available editor
    if not _command_exists(editor):
        for fallback in ["nano", "vi", "notepad"]:
            if _command_exists(fallback):
                editor = fallback
                break

    # Create temp file with code
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        temp_path = f.name

    try:
        # Open editor
        subprocess.run([editor, temp_path], check=True)

        # Read edited code
        with open(temp_path) as f:
            return f.read()
    except subprocess.CalledProcessError:
        print("Editor failed, keeping original code")
        return code
    except FileNotFoundError:
        print(f"Editor '{editor}' not found, keeping original code")
        return code
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _command_exists(cmd: str) -> bool:
    """Check if a command exists in PATH."""
    from shutil import which

    return which(cmd) is not None
