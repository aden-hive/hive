"""Build the visual report: the template with one or more runs' exports embedded."""

from __future__ import annotations

import json
from pathlib import Path

from .export import export_data, prune
from .llm import LLM
from .world import ROOT, RUNS

TEMPLATE = ROOT / "report" / "template.html"


def build(runs: list[tuple[str, str]], out: Path, *, lang: str = "en") -> Path:
    """Write the report for these (run name, label) pairs. Any `lang` but "en" is translated by the model."""
    data: dict = {"runs": {}, "model": LLM().model}
    for name, label in runs:
        run = export_data(RUNS / name)  # in memory: concurrent builds must not share export.json
        prune(run)
        run["label"] = label
        run["physics"] = run["meta"]["physics"]
        findings = RUNS / name / "findings.md"
        run["findings"] = findings.read_text("utf-8") if findings.exists() else ""
        data["runs"][name] = run
    sweep = RUNS / "_sweep" / "sweep.json"
    if sweep.exists():
        rows = json.loads(sweep.read_text("utf-8"))
        data["sweep"], data["sweepDays"] = rows["rows"], rows["days"]
    page = TEMPLATE.read_text("utf-8")
    if lang != "en":
        from .i18n import localize, translate_data

        page = localize(page, lang)  # first, so a stale template fails before any model calls
        data = translate_data(data, lang, LLM(), RUNS / "_i18n" / f"{lang}.json")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = page.replace("__VALE_DATA__", blob)
    out.write_text(html, "utf-8")
    return out
