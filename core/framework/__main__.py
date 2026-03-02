"""Allow running as ``python -m framework``, which powers the ``hive`` console entry point."""

from framework.cli import main

if __name__ == "__main__":
    main()
