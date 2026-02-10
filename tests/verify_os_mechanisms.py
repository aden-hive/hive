
import sys
import subprocess
import tempfile
import os
from pathlib import Path

def verify_temp_path():
    print("\n[CHECK] Temp Path Mechanism...")
    try:
        # replicate the logic used in the fix
        temp_dir = tempfile.gettempdir()
        target_path = Path(temp_dir) / "hive_test_verification"
        print(f"   > System temp dir: {temp_dir}")
        print(f"   > Target test path: {target_path}")
        
        # Verify it's writable
        test_file = target_path / "test.txt"
        os.makedirs(target_path, exist_ok=True)
        test_file.write_text("verification")
        content = test_file.read_text()
        
        if content == "verification":
            print(f"   > [PASS] Successfully wrote to cross-platform temp path.")
        else:
            print(f"   > [FAIL] Content mismatch.")
            
        # cleanup
        try:
            os.remove(test_file)
            os.rmdir(target_path)
        except:
            pass
            
    except Exception as e:
        print(f"   > [FAIL] Temp path logic failed: {e}")
        return False
    return True

def verify_clipboard():
    print("\n[CHECK] Windows Clipboard ('clip')...")
    if sys.platform != "win32":
        print("   > Skipping: Not on Windows")
        return True

    try:
        # Verify 'clip' command exists and runs
        process = subprocess.run(
            ["clip"],
            input=b"Clipboard Verification",
            check=True,
            timeout=5,
            shell=True 
        )
        print("   > [PASS] 'clip' command executed successfully.")
        return True
    except Exception as e:
        print(f"   > [FAIL] 'clip' command failed: {e}")
        return False

if __name__ == "__main__":
    print("=== Cross-Platform Mechanism Verification ===")
    p1 = verify_temp_path()
    p2 = verify_clipboard()
    
    if p1 and p2:
        print("\n[SUCCESS] All mechanisms verified working on this OS.")
        sys.exit(0)
    else:
        print("\n[FAILURE] One or more mechanisms failed.")
        sys.exit(1)
