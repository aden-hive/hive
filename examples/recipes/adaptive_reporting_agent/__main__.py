from agent import AdaptiveReportingAgent

def main():
    agent = AdaptiveReportingAgent()

    # First run: expected to fail
    try:
        agent.run({})
    except Exception as e:
        print(f"First run failed as expected: {e}")

    # Second run: succeeds after adaptation
    result = agent.run({"records": [1, 2, 3]})
    print("Second run result:", result)


if __name__ == "__main__":
    main()
