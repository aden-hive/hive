import pytest
import subprocess
from unittest.mock import MagicMock, patch
# Import your agent tool file
import src.aden_tools.tools.git_client_tool.git_client_tool as git_tool

@pytest.fixture
def mock_mcp():
    mcp = MagicMock()
    mcp.tool.return_value = lambda func: func
    return mcp

@pytest.fixture
def tools(mock_mcp):
    return git_tool.register_tools(mock_mcp)

# -----------------------------
# Unit Tests
# -----------------------------

def test_run_git_success(tools):
    with patch("subprocess.run") as mock_run:
        # 1. ensure_git_repo (success)
        # 2. git_status (success)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="true"),
            MagicMock(returncode=0, stdout="## main\n M file.txt")
        ]
        
        result = tools["git_status"](repo_path=".")
        assert result["ok"] is True
        assert "file.txt" in result["stdout"]

def test_run_git_timeout(tools):
    """Test that timeout is handled gracefully."""
    with patch("subprocess.run") as mock_run:
        # We need side_effect to pass validation then fail execution
        mock_run.side_effect = [
            MagicMock(returncode=0), # 1. ensure_git_repo (Success)
            subprocess.TimeoutExpired(cmd="git status", timeout=5) # 2. The actual command (Fail)
        ]
        
        result = tools["git_status"](repo_path=".")
        
        assert result["ok"] is False
        assert result["error"] == "GIT_TIMEOUT"

def test_ensure_git_repo_failure(tools):
    with patch("subprocess.run") as mock_run:
        # ensure_git_repo fails immediately
        mock_run.return_value.returncode = 128 
        
        result = tools["git_status"](repo_path="/bad/path")
        
        assert result["ok"] is False
        assert result["error"] == "NOT_A_GIT_REPO"

def test_git_diff_truncation(tools):
    fake_output = "\n".join([f"Line {i}" for i in range(600)])
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0), # validation
            MagicMock(returncode=0, stdout=fake_output) # diff
        ]
        
        result = tools["git_diff"]()
        
        assert result["ok"] is True
        assert result["truncated"] is True
        assert len(result["diff"].splitlines()) == 500

def test_git_log_parsing(tools):
    fake_log = "a1b2c3d|Alice|2 hours ago|Fix login bug"

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0), # validation
            MagicMock(returncode=0, stdout=fake_log) # log
        ]
        
        result = tools["git_log"](limit=1)
        
        assert result["ok"] is True
        assert result["commits"][0]["message"] == "Fix login bug"

def test_git_checkout_dirty_tree(tools):
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0), # 1. validation
            MagicMock(returncode=0, stdout="M  file.txt"), # 2. status check (returns content = dirty)
        ]
        
        result = tools["git_checkout"](branch="feature")
        
        assert result["ok"] is False
        assert result["error"] == "DIRTY_WORKING_TREE"

# -----------------------------
# Integration Test
# -----------------------------

@pytest.mark.integration
def test_live_git_workflow(tools, tmp_path):
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    
    def setup_git(args):
        subprocess.run(["git"] + args, cwd=repo_dir, check=True, capture_output=True)

    # Init Repo
    setup_git(["init"])
    # Config is required for commits in CI/Test environments
    setup_git(["config", "user.email", "test@test.com"])
    setup_git(["config", "user.name", "Test User"])
    
    # Commit file
    (repo_dir / "test.txt").write_text("Hello World")
    setup_git(["add", "."])
    setup_git(["commit", "-m", "Initial commit"])
    
    # 1. Test Status
    status = tools["git_status"](repo_path=str(repo_dir))
    assert status["ok"] is True
    # With --branch, even a clean repo shows "## master" or "## main"
    assert "##" in status["stdout"] 
    
    # 2. Test Checkout (New Branch)
    checkout = tools["git_checkout"](branch="dev", create_new=True, repo_path=str(repo_dir))
    assert checkout["ok"] is True
    
    # 3. Verify Branch Switch
    status_branch = tools["git_status"](repo_path=str(repo_dir))
    assert "dev" in status_branch["stdout"]