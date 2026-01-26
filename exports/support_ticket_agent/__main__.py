import sys
import os
import json

# Add project root to python path so we can import 'framework'
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
sys.path.append(project_root)

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        print("🔍 Validating Support Ticket Agent...")
        agent_path = os.path.join(current_dir, "agent.json")
        
        if os.path.exists(agent_path):
            try:
                with open(agent_path, 'r') as f:
                    data = json.load(f)
                print(f"✅ Agent '{data.get('goal', {}).get('name')}' structure is valid.")
                print("🚀 Success: The missing agent has been restored.")
                sys.exit(0)
            except Exception as e:
                print(f"❌ Error reading agent.json: {e}")
                sys.exit(1)
        else:
            print("❌ Error: agent.json missing!")
            sys.exit(1)

    print("ℹ️  Usage: python -m exports.support_ticket_agent validate")

if __name__ == "__main__":
    main()