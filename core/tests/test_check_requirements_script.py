import importlib.util
import json
from pathlib import Path

import pytest


def _load_check_requirements_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "check_requirements.py"
    spec = importlib.util.spec_from_file_location("check_requirements_script", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_main(module, monkeypatch, capsys, argv):
    monkeypatch.setattr(module.sys, "argv", ["check_requirements.py", *argv])
    with pytest.raises(SystemExit) as exc:
        module.main()
    captured = capsys.readouterr()
    stdout = captured.out.strip()
    stderr = captured.err.strip()
    return exc.value.code, stdout, stderr


def test_normalize_module_inputs_splits_trims_and_deduplicates():
    module = _load_check_requirements_module()

    result = module.normalize_module_inputs(
        [
            "json, sys",
            "os",
            "sys, json",
            " , ",
            "",
            "pathlib",
        ]
    )

    assert result == ["json", "sys", "os", "pathlib"]


def test_normalize_module_inputs_keeps_space_separated_usage():
    module = _load_check_requirements_module()

    result = module.normalize_module_inputs(["json", "sys", "os"])

    assert result == ["json", "sys", "os"]


def test_main_accepts_comma_separated_modules(monkeypatch, capsys):
    module = _load_check_requirements_module()
    captured = {}

    def fake_check_imports(modules):
        captured["modules"] = modules
        return {name: "ok" for name in modules}

    monkeypatch.setattr(module, "check_imports", fake_check_imports)
    code, stdout, stderr = _run_main(
        module,
        monkeypatch,
        capsys,
        ["json,sys", " os ", "sys, pathlib"],
    )

    assert code == 0
    assert stderr == ""
    assert captured["modules"] == ["json", "sys", "os", "pathlib"]
    assert json.loads(stdout) == {
        "json": "ok",
        "sys": "ok",
        "os": "ok",
        "pathlib": "ok",
    }


def test_main_rejects_empty_modules_after_normalization(monkeypatch, capsys):
    module = _load_check_requirements_module()

    code, stdout, stderr = _run_main(module, monkeypatch, capsys, [" , ", ","])

    assert code == 1
    assert stdout == ""
    assert json.loads(stderr) == {"error": "No modules specified"}


def test_main_exits_one_when_any_import_fails(monkeypatch, capsys):
    module = _load_check_requirements_module()

    monkeypatch.setattr(
        module,
        "check_imports",
        lambda _modules: {"json": "ok", "definitely_missing": "error: missing"},
    )
    code, stdout, stderr = _run_main(module, monkeypatch, capsys, ["json", "definitely_missing"])

    assert code == 1
    assert stderr == ""
    assert json.loads(stdout) == {
        "json": "ok",
        "definitely_missing": "error: missing",
    }
