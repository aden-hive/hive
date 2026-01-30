from dotenv import load_dotenv
load_dotenv()

"""Allow running as python -m framework"""

from framework.cli import main

if __name__ == "__main__":
    main()
