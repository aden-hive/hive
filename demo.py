import sys
import os

# Add the 'core' folder to the path so it can find 'framework'
sys.path.append(os.path.join(os.getcwd(), "core"))

from framework.graph.code_sandbox import (
    LocalCodeSandbox,
    DockerCodeSandbox,
    SandboxResult,
)


def run_demonstration():
    print("--- Aden Hive Sandbox Blueprint Demo ---")

    # 1. Using the Local Sandbox (The "Old Way", now renamed)
    local = LocalCodeSandbox()
    print("\n[1] Running Local Sandbox:")
    result = local.execute("result = 10 + 20")
    if result.success:
        print(f"Success! Result: {result.result}")

    # 2. Using the Docker Sandbox (The "New Way" we implemented)
    docker = DockerCodeSandbox()
    print("\n[2] Running Docker Sandbox:")
    result = docker.execute("result = 10 + 20")
    if result.success:
        print(f"Success! Result: {result.result}")
    else:
        print(f"Error: {result.error}")
        if result.stdout:
            print(f"Stdout: {result.stdout}")


if __name__ == "__main__":
    try:
        run_demonstration()
    except Exception as e:
        print(f"Error: {e}")
        print("Tip: Ensure you have installed dependencies and Docker is running.")
