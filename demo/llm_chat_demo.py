#!/usr/bin/env python3
"""
RTA-GUARD Demo — Real LLM Chat with Kill-Switch

Connects to a real LLM (OpenAI by default) with DiscusGuard protecting both
input and output. Shows the kill-switch working with actual AI responses.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from discus import DiscusGuard, SessionKilledError, GuardConfig, Severity, RtaEngine
from discus.llm import OpenAIProvider


def main():
    print("=" * 60)
    print("🛡️  RTA-GUARD — Real LLM Chat with Kill-Switch")
    print("=" * 60)
    print()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ Set OPENAI_API_KEY environment variable first.")
        print("   export OPENAI_API_KEY=sk-...")
        sys.exit(1)

    # Initialize guard with RTA
    config = GuardConfig(
        kill_threshold=Severity.HIGH,
        log_all=True
    )
    rta_engine = RtaEngine(config)
    guard = DiscusGuard(config, rta_engine=rta_engine)

    # Register kill callback
    def on_kill(event):
        print(f"\n🚨 SESSION KILLED!")
        print(f"   Type: {event.violation_type}")
        print(f"   Severity: {event.severity}")
        print(f"   Details: {event.details}\n")

    guard.on_kill(on_kill)

    # Initialize LLM with guard
    llm = OpenAIProvider(
        guard=guard,
        api_key=api_key,
        model="gpt-4o-mini"
    )

    session_id = "live-session-001"
    system_prompt = "You are a helpful assistant. Be concise."

    print("Chat started with GPT-4o-mini + DiscusGuard")
    print()
    print("The kill-switch protects both INPUT and OUTPUT:")
    print("  • If you send PII or injection → blocked before reaching LLM")
    print("  • If LLM leaks PII in response → blocked before you see it")
    print()
    print("Try:")
    print("  ✅ Safe:     'What is Python?'")
    print("  🛑 Kill:     'Ignore all previous instructions'")
    print("  🛑 Kill:     'My SSN is 123-45-6789'")
    print()
    print("Type 'quit' to exit, 'stats' to see event log.")
    print("-" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.lower() == "quit":
            break

        if user_input.lower() == "stats":
            events = guard.get_events()
            print(f"\n📊 Event Log ({len(events)} events):")
            for e in events[-10:]:
                marker = {"kill": "🛑", "warn": "⚠️", "pass": "✅"}[e.decision.value]
                print(f"   {marker} [{e.decision.value.upper():4s}] {e.violation_type or 'clean':20s} | {e.details}")
            killed = guard.get_killed_sessions()
            if killed:
                print(f"\n💀 Killed sessions: {killed}")
            continue

        if user_input.lower() == "reset":
            guard.reset_session(session_id)
            guard.reset_session(f"{session_id}:output")
            print("✅ Session reset. You can chat again.")
            continue

        # Check if session is alive
        if not guard.is_session_alive(session_id):
            print("🛑 Your session has been killed. Type 'reset' to start a new one.")
            continue

        # Send to LLM (guard checks input automatically)
        try:
            print("🤖 Thinking...", end="", flush=True)
            response = llm.chat(
                user_input,
                session_id=session_id,
                system_prompt=system_prompt
            )
            print(f"\r🤖 {response}")

        except SessionKilledError as e:
            print(f"\n{'='*60}")
            print(f"🛑 SESSION TERMINATED")
            print(f"   Stage: {'INPUT' if ':output' not in e.event.session_id else 'OUTPUT'}")
            print(f"   Reason: {e.event.violation_type}")
            print(f"   Details: {e.event.details}")
            if ":output" in e.event.session_id:
                print(f"   The LLM tried to return sensitive data. Blocked.")
            else:
                print(f"   Your input was blocked before reaching the AI.")
            print(f"   Type 'reset' to start a new session.")
            print(f"{'='*60}")

        except Exception as e:
            print(f"\r❌ Error: {e}")

    # Final stats
    print("\n" + "=" * 60)
    print("📊 Final Stats:")
    events = guard.get_events()
    kills = len([e for e in events if e.decision.value == "kill"])
    warnings = len([e for e in events if e.decision.value == "warn"])
    passes = len([e for e in events if e.decision.value == "pass"])
    print(f"   Total events: {len(events)}")
    print(f"   Kills: {kills} | Warnings: {warnings} | Passes: {passes}")
    print("=" * 60)


if __name__ == "__main__":
    main()
