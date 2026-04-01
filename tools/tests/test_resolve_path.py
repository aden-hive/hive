import os

import pytest

import coder_tools_server as coder_tools


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """
    Create a temporary PROJECT_ROOT and patch the module to use it.
    """
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(coder_tools, "PROJECT_ROOT", str(root))
    return root

# -----------------------
# Symlink pointing inside project is allowed
# -----------------------
def test_symlink_inside_project(project_root):
    target = project_root / "real.txt"
    target.write_text("data")

    link = project_root / "link.txt"
    link.symlink_to(target)

    resolved = coder_tools._resolve_path("link.txt")

    assert resolved == os.path.abspath(link)


# -----------------------
# Symlink pointing outside project is blocked (security fix)
# -----------------------
def test_symlink_escape_blocked(project_root, tmp_path):
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret")

    link = project_root / "evil_link.txt"
    link.symlink_to(outside_file)

    with pytest.raises(ValueError, match="symlink target outside"):
        coder_tools._resolve_path("evil_link.txt")
