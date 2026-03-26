#!/usr/bin/env python3
"""
RTA-GUARD — REAL LLM Demo (OpenRouter)

This runs the ACTUAL product: DiscusGuard protecting a real LLM conversation.
Not a demo. Not a simulation. Real rules, real kills, real LLM.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from discus import DiscusGuard, SessionKilledError, Severity
from discus.llm import OpenAICompatibleProvider


def main():
    # Check for API key
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: Set OPENROUTER_API_KEY environment variable")
        sys.exit(1)

    print("=" * 60)
    print("🛡️  RTA-GUARD — REAL LLM (OpenRouter)")
    print("=" * 60)
    print()
    print("DiscusGuard is active. Every input goes through 13 rules.")
    print("Type 'quit' to exit.")
    print()

    # Initialize real LLM through RTA-GUARD
    llm = OpenAICompatibleProvider(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        model="google/gemini-2.0-flash-001",  # Fast, cheap model
        # guard is automatically created with DiscusGuard
    )

    session_id = "live-session-1"
    turn = 0

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input or user_input.lower() == "quit":
            print("Goodbye!")
            break

        turn += 1
        print(f"\n[Turn {turn}] Checking through 13 rules...", end="")

        try:
            # This is the REAL call:
            # 1. Input goes through DiscusGuard (13 rules)
            # 2. If safe → sent to LLM
            # 3. If violation → SessionKilledError raised
            response = llm.chat(user_input, session_id=session_id)
            print(" ✅ PASSED")
            print(f"LLM: {response}")
            print()

        except SessionKilledError as e:
            print(f" 🛑 SESSION KILLED")
            print(f"Reason: {e}")
            print()
            print("This session is permanently terminated.")
            print("The kill-switch fired. All further input is blocked.")
            print()
            break

    # Show session events
    print("\n--- Session History ---")
    events = llm.guard.get_events(session_id)
    for i, event in enumerate(events, 1):
        emoji = {"kill": "🛑", "warn": "⚠️", "pass": "✅"}.get(event.decision.value, "❓")
        print(f"{i}. {emoji} [{event.rule_id}] {event.decision.value} — {event.severity.value}")
        if event.details:
            print(f"   Details: {event.details}")

    print(f"\nSession alive: {llm.guard.is_session_alive(session_id)}")


if __name__ == "__main__":
    main()
