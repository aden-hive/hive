import subprocess
import sys
from pathlib import Path
import os

def test_cli():
    print("Testing CLI preview command...")
    
    project_root = Path(__file__).parents[2]
    
    # Run hive preview command via direct module execution
    # We pipeline "n" to stdin to cancel generating scaffold after preview
    # We must ensurePYTHONPATH includes core
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{project_root}/core:{env.get('PYTHONPATH', '')}"
    
    cmd = [
        sys.executable, "core/framework/cli.py", 
        "preview", 
        "Create a simple calculator agent", 
        "--name", "CalculatorAgent",
        "--criteria", "Calculate 2+2"
    ]
    
    # We pass 'n' to stdin to exit the interactive prompt asking "Proceed (Generate Scaffold)?"
    # The prompt might wait for input.
    process = subprocess.Popen(
        cmd, 
        stdin=subprocess.PIPE, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(project_root),
        env=env
    )
    
    stdout, stderr = process.communicate(input="n\n")
    
    print("STDOUT:\n", stdout)
    if stderr:
        print("STDERR:\n", stderr)
    
    if "Generating preview for goal" in stdout and "Proposed Nodes" in stdout:
        print("\nCLI Test Passed: Preview generated and displayed.")
    else:
        print("\nCLI Test Failed: Output expectation not met.")
        sys.exit(1)

if __name__ == "__main__":
    test_cli()
