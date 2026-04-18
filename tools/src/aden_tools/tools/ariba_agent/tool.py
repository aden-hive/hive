
# hive/tools/src/aden_tools/tools/ariba_agent/tool.py

from fastmcp import FastMCP
from typing import Dict, List

from .ariba_client import AribaClient
from .semantic_filter import filter_opportunities, classify_tech_moat
from .scoring import score_opportunity
from .draft_generator import generate_rfi_draft


def register_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def search_ariba_opportunities(query: Dict) -> Dict:
        """
        Discover and score SAP Ariba opportunities using semantic filtering.
        """
        try:
            client = AribaClient()

            raw_results = await client.search_async(query)

            filtered = filter_opportunities(raw_results)

            results: List[Dict] = []

            for opp in filtered:
                score = score_opportunity(opp)

                opp["confidence_score"] = score
                opp["tech_moat"] = classify_tech_moat(
                    opp.get("description", "")
                )

                if score > 0.85:
                    opp["hitl_required"] = True
                    opp["draft_rfi"] = generate_rfi_draft(opp)
                else:
                    opp["hitl_required"] = False

                results.append(opp)

            return {
                "results": results,
                "total": len(results),
            }

        except Exception as e:
            return {"error": str(e)}
