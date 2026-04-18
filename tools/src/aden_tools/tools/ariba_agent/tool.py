from __future__ import annotations

from typing import Dict, List

from fastmcp import FastMCP

from .ariba_client import AribaClient
from .draft_generator import generate_rfi_draft
from .scoring import score_opportunity
from .semantic_filter import classify_tech_moat, filter_opportunities

_client = AribaClient()


def register_tools(mcp: FastMCP) -> None:
    """
    Register MCP tools for Ariba procurement automation.
    """

    @mcp.tool()
    async def search_ariba_opportunities(query: Dict[str, object]) -> Dict[str, object]:
        """
        Search, filter, score, and enrich SAP Ariba opportunities.

        Args:
            query: Structured query dict.

        Returns:
            Dict containing results and total count OR error.
        """
        try:
            raw_results = await _client.search_async(query)
            filtered = filter_opportunities(raw_results)

            results: List[Dict[str, object]] = []

            for opp in filtered:
                score = score_opportunity(opp)
                opp["confidence_score"] = score
                opp["tech_moat"] = classify_tech_moat(
                    str(opp.get("description", ""))
                )

                if score >= 0.85:
                    opp["hitl_required"] = True
                    opp["draft_rfi"] = generate_rfi_draft(opp)
                else:
                    opp["hitl_required"] = False

                results.append(opp)

            return {"results": results, "total": len(results)}

        except Exception as e:
            return {"error": "processing_failed", "message": str(e)}
