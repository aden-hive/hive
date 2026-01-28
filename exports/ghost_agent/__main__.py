import sys
import os
import asyncio

try:
    from framework.runner import AgentRunner
except ImportError as e:
    print(f"❌ Critical Error: Could not import framework. {e}")
    sys.exit(1)

async def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))

    print(f"🤖 Booting Basic Template Agent...")
    print(f"   Directory: {current_dir}")

    try:
        # Load the agent
        runner = AgentRunner.load(current_dir, mock_mode=True)
        print("✅ Agent loaded successfully.")

        # Run the agent
        print("🚀 Executing workflow...")
        result = await runner.run(
            input_data={"user_message": "Hello World"}
        )

        if result.success:
            print(f"\n✅ Execution Succeeded!")
            print(f"   Output: {result.output}")
        else:
            print(f"\n❌ Execution Failed: {result.error}")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
