from __future__ import annotations

import argparse
import json

from fastmcp import FastMCP

from aden_tools.tools.mcp_helpers import get_tool_fn
from aden_tools.tools.office_skills_pack import register_office_skills_pack


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--spec", required=True, help="Path to pack JSON spec")
    p.add_argument("--workspace", default="demo-ws")
    p.add_argument("--agent", default="demo-agent")
    p.add_argument("--session", default="demo-session")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--print-markdown", action="store_true")
    args = p.parse_args(argv)

    spec = json.loads(open(args.spec, "r", encoding="utf-8").read())
    if args.dry_run:
        spec["dry_run"] = True

    mcp = FastMCP("office-pack-cli")
    register_office_skills_pack(mcp)

    pack = get_tool_fn(mcp, "office_pack_generate")

    res = pack(
        pack=spec,
        workspace_id=args.workspace,
        agent_id=args.agent,
        session_id=args.session,
    )

    print(json.dumps(res, indent=2))
    if args.print_markdown and res.get("success"):
        view = get_tool_fn(mcp, "office_pack_view_markdown")
        items = res.get("metadata", {}).get("manifest", [])
        md = view(title="Office Pack Output", items=items)
        print("\n" + md["markdown"])
    return 0 if res.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
