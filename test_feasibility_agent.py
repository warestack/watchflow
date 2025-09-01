#!/usr/bin/env python3
"""
Test script for RuleFeasibilityAgent
Run this to test the agent's feasibility analysis and YAML generation capabilities.
"""

import asyncio
import os
import sys

# Add src to path
sys.path.append("src")

from dotenv import load_dotenv

from agents.feasibility_agent.agent import RuleFeasibilityAgent

# Load environment variables
load_dotenv()


async def test_feasibility_agent():
    """Test the RuleFeasibilityAgent with various rule descriptions."""

    # Initialize the agent
    agent = RuleFeasibilityAgent()

    # Test cases
    test_rules = [
        "All pull requests must have at least 3 approvals from senior developers",
        "No commits should be pushed directly to main branch",
        "All commit messages must follow Conventional Commits format",
        "Files larger than 10MB should not be committed",
        "Pull request titles must start with feat:, fix:, or docs:",
        "Only allow deployments during business hours (9 AM - 6 PM)",
        "Require code review from at least one team lead for security-related changes",
    ]

    print("🧪 Testing RuleFeasibilityAgent\n")
    print("=" * 60)

    for i, rule_description in enumerate(test_rules, 1):
        print(f"\n📋 Test Case {i}: {rule_description}")
        print("-" * 50)

        try:
            # Execute the agent
            result = await agent.execute(rule_description)

            print(f"✅ Status: {result.status}")
            print(f"📊 Feasibility: {result.data.get('is_feasible', 'Unknown')}")

            if result.data.get("yaml_config"):
                print("📝 Generated YAML:")
                print(result.data["yaml_config"])
            else:
                print("❌ No YAML generated")

            if result.data.get("reasoning"):
                print(f"💭 Reasoning: {result.data['reasoning']}")

        except Exception as e:
            print(f"❌ Error: {str(e)}")
            print(f"🔍 Error type: {type(e).__name__}")

        print()


async def main():
    """Main function to run the tests."""
    print("🚀 Starting RuleFeasibilityAgent tests...")
    print(f"🔑 OpenAI API Key: {'✅ Set' if os.getenv('OPENAI_API_KEY') else '❌ Missing'}")
    print(f"🤖 Model: {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}")

    try:
        await test_feasibility_agent()
        print("\n🎉 All tests completed!")
    except Exception as e:
        print(f"\n💥 Test suite failed: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
