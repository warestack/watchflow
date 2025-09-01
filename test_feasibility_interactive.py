#!/usr/bin/env python3
"""
Interactive test script for RuleFeasibilityAgent
Input your own rule descriptions and see how the agent evaluates them.
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


async def test_single_rule(rule_description: str):
    """Test a single rule description."""
    print(f"\n🧪 Testing: {rule_description}")
    print("=" * 60)

    try:
        # Initialize the agent
        agent = RuleFeasibilityAgent()

        # Execute the agent
        result = await agent.execute(rule_description)

        print(f"✅ Status: {result.status}")
        print(f"📊 Feasibility: {result.data.get('is_feasible', 'Unknown')}")

        if result.data.get("reasoning"):
            print("\n💭 Feasibility Analysis:")
            print(result.data["reasoning"])

        if result.data.get("yaml_config"):
            print("\n📝 Generated YAML Configuration:")
            print("```yaml")
            print(result.data["yaml_config"])
            print("```")
        else:
            print("\n❌ No YAML configuration generated")

        if result.data.get("confidence_score"):
            print(f"\n🎯 Confidence Score: {result.data['confidence_score']}")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print(f"🔍 Error type: {type(e).__name__}")
        import traceback

        traceback.print_exc()


async def interactive_mode():
    """Run in interactive mode for custom rule testing."""
    print("🎯 Interactive RuleFeasibilityAgent Tester")
    print("=" * 50)
    print("Enter rule descriptions to test feasibility analysis")
    print("Type 'quit' to exit, 'examples' for sample rules")
    print()

    while True:
        try:
            rule_input = input("\n📝 Enter rule description: ").strip()

            if rule_input.lower() == "quit":
                print("👋 Goodbye!")
                break

            elif rule_input.lower() == "examples":
                print("\n📚 Example rules to test:")
                examples = [
                    "All PRs must have at least 2 approvals",
                    "No direct pushes to main branch",
                    "Commit messages must follow Conventional Commits",
                    "Files larger than 5MB should not be committed",
                    "Only allow deployments during business hours",
                    "Require security review for sensitive files",
                ]
                for i, example in enumerate(examples, 1):
                    print(f"  {i}. {example}")
                continue

            elif not rule_input:
                print("⚠️  Please enter a rule description")
                continue

            await test_single_rule(rule_input)

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            print("\n\n👋 Goodbye!")
            break


async def main():
    """Main function."""
    print("🚀 RuleFeasibilityAgent Interactive Tester")
    print(f"🔑 OpenAI API Key: {'✅ Set' if os.getenv('OPENAI_API_KEY') else '❌ Missing'}")
    print(f"🤖 Model: {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}")

    if not os.getenv("OPENAI_API_KEY"):
        print("\n❌ Please set OPENAI_API_KEY in your .env file")
        return

    try:
        await interactive_mode()
    except Exception as e:
        print(f"\n💥 Tester failed: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
