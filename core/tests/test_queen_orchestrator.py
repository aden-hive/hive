from __future__ import annotations

from framework.server.queen_orchestrator import (
    _build_worker_terminal_notification,
    _select_primary_worker_result,
)


def test_select_primary_worker_result_prefers_result_over_input_like_keys() -> None:
    output = {
        "task": "Solve this word problem using strict Given/Steps/Answer format.",
        "givens": "Item prices and discount rule.",
        "final_value": "₹2,295",
        "result": (
            "Given:\n- Item prices: ₹850, ₹1,200, ₹650\n\n"
            "Steps:\n1) Add prices.\n2) Apply discount.\n\n"
            "Answer:\n₹2,295"
        ),
    }

    assert _select_primary_worker_result(output) == (
        "result",
        output["result"],
    )


def test_worker_terminal_notification_embeds_primary_result_verbatim() -> None:
    result = (
        "Given:\n- Item prices: ₹850, ₹1,200, ₹650\n\n"
        "Steps:\n1) Add prices.\n2) Apply discount.\n\n"
        "Answer:\n₹2,295"
    )
    notification = _build_worker_terminal_notification(
        {
            "task": "Solve the problem.",
            "final_value": "₹2,295",
            "result": result,
        }
    )

    assert "Primary result key: result" in notification
    assert "[PRIMARY_RESULT_BEGIN]" in notification
    assert result in notification
    assert "Do not paraphrase, compress, or reformat it." in notification


def test_worker_terminal_notification_does_not_treat_artifact_filename_as_primary_result() -> None:
    notification = _build_worker_terminal_notification(
        {
            "research_brief": "AI news roundup from the past week.",
            "articles_data": "[Saved to 'output_articles_data.json' (3957 bytes).]",
            "report_file": "tech_news_report.html",
        }
    )

    assert "[PRIMARY_RESULT_BEGIN]" not in notification
    assert "report_file: tech_news_report.html" in notification
