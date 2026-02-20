import asyncio

from framework.runner import AgentRunner


async def main():
    print("=" * 64)
    print("  💰  REVENUE LEAK DETECTOR — Starting Agent")
    print("=" * 64)

    runner = AgentRunner.load("examples/templates/revenue_leak_detector")
    runner._setup()

    result = await runner.run(input_data={"cycle": "0"})

    path = result.path
    path_str = " -> ".join(path) if isinstance(path, list) else str(path or "")
    steps = len(path) if isinstance(path, list) else (len(path_str.split(" -> ")) if path_str else 0)

    print("=" * 64)
    print(f"  Result   : {'SUCCESS ✅' if result.success else 'FAILED ❌'}")
    print(f"  Path     : {path_str}")
    print(f"  Steps    : {steps}")
    print(f"  Quality  : {result.execution_quality}")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
