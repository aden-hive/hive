"""Entry-point module, in case you use `python -m griffe`.

Why does this file exist, and why `__main__`? For more info, read:

- https://www.python.org/dev/peps/pep-0338/
- https://docs.python.org/3/using/cmdline.html#cmdoption-m
"""

import sys

try:
    from griffecli import main
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "`griffecli` or its dependencies are not installed. Install `griffecli` to use `python -m griffe`.",
    ) from exc

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
