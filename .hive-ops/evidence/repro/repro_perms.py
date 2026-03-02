import os
import json
from pathlib import Path

test_file = Path("test_perms.json")
if test_file.exists():
    test_file.unlink()

# Simulate default write
with open(test_file, "w") as f:
    json.dump({"token": "secret"}, f)

mode = oct(os.stat(test_file).st_mode & 0o777)
print(f"Default permissions: {mode}")

test_file.unlink()

# Simulate 0600 write
flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
with os.fdopen(os.open(test_file, flags, 0o600), "w") as f:
    json.dump({"token": "secret"}, f)

mode = oct(os.stat(test_file).st_mode & 0o777)
print(f"Restricted permissions (0600): {mode}")

test_file.unlink()
