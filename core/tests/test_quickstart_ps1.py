from pathlib import Path

QUICKSTART_PS1 = Path(__file__).resolve().parents[2] / "quickstart.ps1"
CHECK_LLM_KEY_SNIPPET = '(Join-Path $ScriptDir "scripts/check_llm_key.py")'


def _quickstart_text() -> str:
    return QUICKSTART_PS1.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_all_check_llm_key_invocations_use_scriptdir_join_path():
    text = _quickstart_text()
    invocation_lines = [line.strip() for line in text.splitlines() if "check_llm_key.py" in line]

    assert invocation_lines
    for line in invocation_lines:
        assert CHECK_LLM_KEY_SNIPPET in line


def test_hive_llm_health_check_uses_uv_run_python():
    text = _quickstart_text()
    start = text.index("# For Hive LLM: prompt for API key with verification + retry")
    end = text.index("# Prompt for model if not already selected (manual provider path)")
    hive_block = text[start:end]

    assert "$PythonCmd scripts/check_llm_key.py hive" not in hive_block
    assert (
        '& $UvCmd run python (Join-Path $ScriptDir "scripts/check_llm_key.py") '
        'hive $apiKey "$HiveLlmEndpoint"'
    ) in hive_block
