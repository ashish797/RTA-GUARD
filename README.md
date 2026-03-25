# RTA-GUARD — NeMo + Kill-Switch

The seatbelt for AI. Detects violations. Kills sessions. Logs everything.

## What Is This?

RTA-GUARD wraps your AI application and adds a **deterministic kill-switch**. When a violation is detected (PII leak, prompt injection, jailbreak attempt), the session is terminated instantly — not just filtered.

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Run the demo
python demo/chat_demo.py

# Start the dashboard
python -m dashboard.app
```

## How It Works

```
Your App → RTA-GUARD (Discus) → NeMo Guardrails → LLM API
                    │
                    ├── Safe? → ✅ Pass through
                    └── Violation? → 🛑 Kill session + log
```

## Integration (3 lines)

```python
from discus import DiscusGuard

guard = DiscusGuard()
response = guard.check_and_forward(user_input, session_id="abc123")
# Returns response or raises SessionKilledError
```

## Dashboard

Visit `http://localhost:8000` to see:
- Blocked sessions in real-time
- Violation types and severity
- Session history

## Project Structure

```
rta-guard-mvp/
├── discus/           # Core kill-switch interceptor
│   ├── guard.py      # Main DiscusGuard class
│   ├── rules.py      # Rule engine
│   └── models.py     # Data models
├── dashboard/        # Web dashboard
│   ├── app.py        # FastAPI server
│   └── static/       # Frontend assets
├── rules/            # Default rule configurations
│   └── default.yaml
├── tests/            # Tests
├── demo/             # Demo chat app
│   └── chat_demo.py
└── docker-compose.yml
```

## License

Apache 2.0
