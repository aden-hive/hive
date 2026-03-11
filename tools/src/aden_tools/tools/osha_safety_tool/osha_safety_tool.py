from fastmcp import FastMCP

def register_tools(mcp: FastMCP) -> None:
    """Register OSHA safety tools with the MCP server."""

    @mcp.tool()
    def check_osha_compliance(violation_description: str) -> dict:
        """
        Cross-reference a safety violation detected by the vision system with OSHA regulations.

        Use this tool when the vision system (like YOLO) detects a missing safety 
        item (e.g., hard hat, safety vest) and you need the official OSHA regulation code.

        Args:
            violation_description: A short string describing the missing safety gear.

        Returns:
            Dict containing the safety status, exact OSHA regulation code, and a warning message.
        """
        violation = violation_description.lower().strip()

        
        osha_database = {
            # Head & Face
            "no hard hat": {
                "code": "OSHA 1926.100(a)",
                "message": "Employees working in areas where there is a possible danger of head injury from impact, or from falling or flying objects, shall be protected by protective helmets."
            },
            "missing goggles": {
                "code": "OSHA 1926.102(a)(1)",
                "message": "The employer shall ensure that each affected employee uses appropriate eye or face protection when exposed to eye or face hazards."
            },
            # Visibility
            "no safety vest": {
                "code": "OSHA 1926.201(a)",
                "message": "Flaggers and workers exposed to vehicular traffic shall wear warning garments such as red or orange vests."
            },
            # Fall Protection & Scaffolding
            "no harness": {
                "code": "OSHA 1926.501(b)(1)",
                "message": "Each employee on a walking/working surface with an unprotected side or edge which is 6 feet or more above a lower level shall be protected from falling by personal fall arrest systems."
            },
            "missing guardrail": {
                "code": "OSHA 1926.451(g)(1)",
                "message": "Each employee on a scaffold more than 10 feet above a lower level shall be protected from falling to that lower level."
            },
            # Footwear & General PPE
            "improper footwear": {
                "code": "OSHA 1926.95(a)",
                "message": "Protective equipment, including personal protective equipment for extremities, shall be provided, used, and maintained in a sanitary and reliable condition."
            }
        }

        if violation in osha_database:
            data = osha_database[violation]
            return {
                "status": "VIOLATION_CONFIRMED",
                "violation": violation_description,
                "osha_code": data["code"],
                "regulation_text": data["message"]
            }
        else:
            return {
                "status": "UNKNOWN_VIOLATION",
                "violation": violation_description,
                "osha_code": "N/A",
                "regulation_text": "Violation not found in primary database."
            }
