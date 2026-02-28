import importlib.metadata as md


def test_cli_entrypoint_exists() -> None:
    eps = md.entry_points(group="console_scripts")
    names = {e.name for e in eps}
    assert "aden-office-pack" in names
