import subprocess
import sys


def run(cmd):
    print(">", " ".join(cmd))
    subprocess.check_call(cmd)


if __name__ == "__main__":
    run(
        [
            sys.executable,
            "-m",
            "aden_tools.cli.office_pack",
            "--spec",
            "tools/examples/pack_finance.json",
        ]
    )
