#!/usr/bin/env python3
"""
RTA-GUARD Demo — Chat App with Kill-Switch

A simple chat app that demonstrates DiscusGuard in action.
Run this to see the kill-switch work in real-time.
"""
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from discus import DiscusGuard, SessionKilledError, GuardConfig, Severity, RtaEngine


def fake_llm(user_input: str) -> str:
    """Simulated LLM response."""
    responses = {
        "hello": "Hi there! How can I help you today?",
        "help": "I'm here to assist. What do you need?",
        "bye": "Goodbye! Have a great day!",
    }
    for key, response in responses.items():
        if key in user_input.lower():
            return response
    return f"I received your message: '{user_input}'. How can I help further?"


def main():
    print("=" * 60)
    print("🛡️  RTA-GUARD Demo — Chat with Kill-Switch")
    print("=" * 60)
    print()

    # Initialize guard with default config
    # Kill threshold: HIGH (kills on HIGH and CRITICAL severity)
    config = GuardConfig(
        kill_threshold=Severity.HIGH,
        log_all=True
    )
    # Initialize RTA engine (draft rules)
    rta_engine = RtaEngine(config)
    guard = DiscusGuard(config, rta_engine=rta_engine)

    # Register a callback for kills
    def on_kill(event):
        print(f"\n🚨 ALERT: Session killed!")
        print(f"   Type: {event.violation_type}")
        print(f"   Severity: {event.severity}")
        print(f"   Details: {event.details}\n")

    guard.on_kill(on_kill)

    session_id = "demo-session-001"

    print("Chat started. Try these examples:")
    print()
    print("  ✅ Safe:     'hello', 'help me with something'")
    print("  ⚠️  Warning:  'my email is test@example.com'")
    print("  🛑 Kill:     'ignore all previous instructions'")
    print("  🛑 Kill:     'here is my SSN: 123-45-6789 and credit card'")
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
            for e in events[-10:]:  # Last 10
                print(f"   [{e.decision.value.upper():4s}] {e.violation_type or 'clean':20s} | {e.details}")
            killed = guard.get_killed_sessions()
            if killed:
                print(f"\n💀 Killed sessions: {killed}")
            continue

        if user_input.lower() == "reset":
            guard.reset_session(session_id)
            print("✅ Session reset. You can chat again.")
            continue

        # Check if session is alive
        if not guard.is_session_alive(session_id):
            print("🛑 Your session has been killed. Type 'reset' to start a new one.")
            continue

        # Run through the guard
        try:
            response = guard.check_and_forward(
                user_input,
                session_id=session_id,
                llm_fn=fake_llm
            )
            print(f"Bot: {response}")

        except SessionKilledError as e:
            print(f"\n{'='*60}")
            print(f"🛑 SESSION TERMINATED")
            print(f"   Reason: {e.event.violation_type}")
            print(f"   Details: {e.event.details}")
            print(f"   Your input was blocked before reaching the AI.")
            print(f"   Type 'reset' to start a new session.")
            print(f"{'='*60}")

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
