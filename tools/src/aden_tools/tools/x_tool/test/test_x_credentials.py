from aden_tools.credentials.integrations import INTEGRATION_CREDENTIALS


def test_x_credential_spec_exists():
    assert "x" in INTEGRATION_CREDENTIALS
    spec = INTEGRATION_CREDENTIALS["x"]

    assert spec.env_var == "X_BEARER_TOKEN"
    assert "x_post_tweet" in spec.tools
