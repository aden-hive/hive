#!/usr/bin/env python3
"""
Slack Tool Test Script

Usage:
    1. Set SLACK_BOT_TOKEN in your .env or environment
    2. Run: python test_slack_manual.py

Steps:
    1. Tests authentication
    2. Lists available channels
    3. (Optional) Sends a test message if you provide a channel ID
"""

import os
import sys

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv("/Users/levinms/Desktop/Work/Aden/.env")
except ImportError:
    pass

# Add the tools package to path
sys.path.insert(0, "/Users/levinms/Desktop/Work/Aden/hive/tools/src")

from aden_tools.tools.slack_tool.slack_tool import _SlackClient


def main():
    # Get token
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        print("❌ SLACK_BOT_TOKEN not found in environment!")
        print("   Add it to your .env file:")
        print("   SLACK_BOT_TOKEN=xoxb-your-token-here")
        sys.exit(1)

    print(f"🔑 Token found: {token[:15]}...{token[-4:]}")
    client = _SlackClient(token)

    # Step 1: Test auth
    print("\n📡 Testing authentication...")
    auth_result = client.auth_test()
    if "error" in auth_result:
        print(f"❌ Auth failed: {auth_result['error']}")
        sys.exit(1)
    print(f"✅ Connected as: @{auth_result.get('user')} in {auth_result.get('team')}")
    print(f"   Bot ID: {auth_result.get('bot_id')}")

    # Step 2: List channels
    print("\n📋 Listing channels...")
    channels_result = client.list_conversations()
    if "error" in channels_result:
        print(f"❌ Failed to list channels: {channels_result['error']}")
    else:
        channels = channels_result.get("channels", [])
        print(f"✅ Found {len(channels)} channels:")
        for ch in channels[:10]:  # Show first 10
            private_icon = "🔒" if ch.get("is_private") else "📢"
            print(f"   {private_icon} #{ch['name']} (ID: {ch['id']})")
        if len(channels) > 10:
            print(f"   ... and {len(channels) - 10} more")

    # Step 3: Send test message (optional)
    print("\n" + "=" * 50)
    channel_id = input("Enter channel ID to send test message (or press Enter to skip): ").strip()
    
    if channel_id:
        print(f"\n📤 Sending test message to {channel_id}...")
        result = client.post_message(
            channel=channel_id,
            text="You have been Meowedddd from test messages"
        )
        if "error" in result:
            print(f"❌ Failed: {result['error']}")
        else:
            print(f"✅ Message sent! Timestamp: {result.get('ts')}")
            
            # Add a reaction to the message we just sent
            print("\n😊 Adding reaction to message...")
            reaction_result = client.add_reaction(
                channel=channel_id,
                timestamp=result.get("ts"),
                name="bee"  # 🐝
            )
            if "error" in reaction_result:
                print(f"⚠️  Reaction failed (emoji may not exist): {reaction_result['error']}")
            else:
                print("✅ Reaction added!")
    else:
        print("Skipped message send.")

    print("\n🎉 Test complete!")


if __name__ == "__main__":
    main()
