"""Load testing with Locust."""

from locust import HttpUser, task, between, events
from locust.runners import MasterRunner
import time


class AgentUser(HttpUser):
    """Simulate agent service users."""

    wait_time = between(1, 3)

    @task(3)
    def create_agent(self):
        """Test agent creation endpoint."""
        response = self.client.post(
            "/api/v1/agents",
            json={
                "name": "Test Agent",
                "goal": "Test goal",
                "nodes": []
            }
        )
        assert response.status_code in [201, 401]

    @task(5)
    def get_agents(self):
        """Test list agents endpoint."""
        response = self.client.get("/api/v1/agents")
        assert response.status_code in [200, 401]

    @task(2)
    def execute_agent(self):
        """Test agent execution endpoint."""
        response = self.client.post("/api/v1/agents/test-agent/execute")
        assert response.status_code in [200, 202, 404]


class AuthUser(HttpUser):
    """Simulate auth service users."""

    wait_time = between(1, 2)

    @task(5)
    def login(self):
        """Test login endpoint."""
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "user@example.com",
                "password": "password123"
            }
        )
        assert response.status_code in [200, 401]

    @task(3)
    def register(self):
        """Test registration endpoint."""
        response = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": f"test{int(time.time())}@example.com",
                "password": "password123",
                "name": "Test User"
            }
        )
        assert response.status_code in [201, 400]


class ConfigUser(HttpUser):
    """Simulate config service users."""

    wait_time = between(1, 3)

    @task(4)
    def get_configs(self):
        """Test get configs endpoint."""
        response = self.client.get("/api/v1/config/production/agent-service")
        assert response.status_code in [200, 401]

    @task(2)
    def evaluate_feature_flag(self):
        """Test feature flag evaluation."""
        response = self.client.post(
            "/api/v1/feature-flags/test_flag/evaluate",
            json={"user_attributes": {"user_id": "test"}}
        )
        assert response.status_code in [200, 404]

    @task(1)
    def set_config(self):
        """Test set config endpoint."""
        response = self.client.post(
            "/api/v1/config/production/test-service/test-key",
            json={"value": "test"}
        )
        assert response.status_code in [201, 401]


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Output test results summary."""
    if not isinstance(environment.runner, MasterRunner):
        print("\n" + "="*50)
        print("Load Test Results:")
        print(f"Total requests: {environment.runner.stats.total.num_requests}")
        print(f"Failures: {environment.runner.stats.total.num_failures}")
        print(f"RPS: {environment.runner.stats.total.avg_rps}")
        print("="*50 + "\n")
