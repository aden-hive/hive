import json
import argparse


def main():
    parser = argparse.ArgumentParser(description="Hello Agent (Example)")
    parser.add_argument(
        "--input",
        type=str,
        default="{}",
        help='JSON input string (example: \'{"name":"Priyanshu"}\')',
    )
    args = parser.parse_args()

    try:
        data = json.loads(args.input)
    except json.JSONDecodeError:
        data = {}

    name = data.get("name", "World")
    print(f"👋 Hello, {name}! This is a minimal example agent from exports/.")


if __name__ == "__main__":
    main()
