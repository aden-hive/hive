from framework.graph.code_sandbox import LocalCodeSandbox, DockerCodeSandbox, SandboxResult

def run_demonstration():
    print("--- Aden Hive Sandbox Blueprint Demo ---")
    
    # 1. Using the Local Sandbox (The "Old Way", now renamed)
    local = LocalCodeSandbox()
    print("\n[1] Running Local Sandbox:")
    result = local.execute("result = 10 + 20")
    if result.success:
        print(f"Success! Result: {result.result}")
    
    # 2. Using the Docker Sandbox (The "New Way" we proposed)
    docker = DockerCodeSandbox()
    print("\n[2] Running Docker Sandbox:")
    result = docker.execute("result = 10 + 20")
    if not result.success:
        print(f"Status: {result.error}")
        print("(This is expected because we only built the blueprint so far!)")

if __name__ == "__main__":
    # Add the current folder to the path so it can find 'framework'
    import sys
    import os
    sys.path.append(os.path.join(os.getcwd(), "core/src"))
    
    try:
        run_demonstration()
    except ImportError as e:
        print(f"Error: {e}")
        print("Tip: We need to install dependencies like 'pydantic' to run the full framework.")
