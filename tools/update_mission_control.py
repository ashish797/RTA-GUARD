#!/usr/bin/env python3
"""
RTA-GUARD — Mission Control Auto-Updater

Scans the repository state (commits, files, phases) and regenerates
the Mission Control page with accurate progress.

Run as: python tools/update_mission_control.py
Output: mission-control/index.html (updated)
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path
import subprocess

# Project root
ROOT = Path(__file__).parent.parent  # rta-guard-mvp directory


def run_git(*args):
    """Run a git command and return output."""
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def get_git_branch():
    """Get current branch."""
    return run_git("branch", "--show-current")


def get_commit_count():
    """Total number of commits on current branch."""
    count = run_git("rev-list", "--count", "HEAD")
    return int(count) if count.isdigit() else 0


def get_commits_since(phase_tag):
    """Check if a phase tag exists and if we have commits beyond it."""
    # For now, use commit messages to determine phase completion
    log = run_git("log", "--oneline", "--all")
    return log


def parse_phase_status():
    """
    Determine phase status by scanning commit messages and file presence.
    Returns a dict: {phase_num: {"status": "done|current|todo", "tasks": {...}}}
    """
    phases = {
        0: {"status": "todo", "tasks": {}},
        1: {"status": "todo", "tasks": {}},
        2: {"status": "todo", "tasks": {}},
        3: {"status": "todo", "tasks": {}},
        4: {"status": "todo", "tasks": {}},
        5: {"status": "todo", "tasks": {}},
        6: {"status": "todo", "tasks": {}},
    }

    # Check Phase 0 completeness
    phase0_files = [
        "discus/guard.py",
        "discus/rules.py",
        "discus/models.py",
        "dashboard/app.py",
        "tests/test_discus.py",
        "requirements.txt",
        "docker-compose.yml",
        "showcase/index.html"
    ]
    phase0_complete = all((ROOT / f).exists() for f in phase0_files)
    phases[0]["status"] = "done" if phase0_complete else "todo"

    # Check Phase 1 progress
    phase1_files = [
        "docs/RTA-RULESET.md",
        "discus/rta_engine.py"
    ]
    phase1_has_rules = (ROOT / "docs/RTA-RULESET.md").exists()
    phase1_has_engine = (ROOT / "discus/rta_engine.py").exists()
    if phase1_has_rules and phase1_has_engine:
        phases[1]["status"] = "done"
    elif phase1_has_rules or phase1_has_engine:
        phases[1]["status"] = "current"
    else:
        phases[1]["status"] = "todo"

    # Phases 2-6 are not started yet
    for p in range(2, 7):
        phases[p]["status"] = "todo"

    return phases


def count_completed_tasks():
    """Count completed major milestones across all phases."""
    completed = 0

    # Phase 0 tasks (count files as proxies)
    phase0_tasks = [
        "discus/guard.py", "discus/rules.py", "discus/models.py",
        "dashboard/app.py", "dashboard/auth.py", "tests/test_discus.py",
        "requirements.txt", "docker-compose.yml", "showcase/index.html",
        "demo/chat_demo.py", "demo/llm_chat_demo.py", "discus/llm.py",
        "discus/nemo.py"
    ]
    completed += sum(1 for f in phase0_tasks if (ROOT / f).exists())

    # Phase 1 tasks
    phase1_tasks = [
        "docs/RTA-RULESET.md",
        "discus/rta_engine.py"
    ]
    completed += sum(1 for f in phase1_tasks if (ROOT / f).exists())

    return completed


def generate_html(phases, completed_tasks, total_tasks=50):
    """Generate the Mission Control HTML page."""
    html_path = ROOT / "rta-guard-mvp" / "docs" / "MISSION-CONTROL.html"
    if not html_path.parent.exists():
        html_path.parent.mkdir(parents=True)

    current_phase = next((i for i, p in phases.items() if p["status"] == "current"), 0)
    complete_phases = sum(1 for p in phases.values() if p["status"] == "done")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M IST")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RTA-GUARD Mission Control</title>
    <style>
        /* ... (same CSS as before) ... */
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'SF Mono', 'Consolas', 'Monaco', monospace; background: #050505; color: #e0e0e0; }}
        .header {{
            background: linear-gradient(135deg, #0a0a1a 0%, #1a1a3e 100%);
            padding: 40px 30px;
            border-bottom: 2px solid #e94560;
            text-align: center;
        }}
        .header h1 {{ font-size: 2em; color: #e94560; margin-bottom: 10px; }}
        .header .subtitle {{ color: #4ecdc4; font-size: 1.2em; margin-bottom: 5px; }}
        .header .tagline {{ color: #888; font-size: 0.95em; }}
        .status-badge {{
            display: inline-block;
            padding: 8px 20px;
            background: #00ff8833;
            color: #00ff88;
            border: 1px solid #00ff88;
            border-radius: 20px;
            margin-top: 15px;
            font-size: 0.9em;
            font-weight: bold;
        }}
        .live {{ background: #e9456033; color: #e94560; border-color: #e94560; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 30px; }}
        .section {{ margin-bottom: 40px; }}
        .section-title {{
            color: #4ecdc4;
            font-size: 1.3em;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #333;
        }}
        .phase {{ margin-bottom: 25px; }}
        .phase-header {{
            display: flex;
            align-items: center;
            margin-bottom: 10px;
        }}
        .phase-icon {{
            width: 30px; height: 30px;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            margin-right: 15px; font-weight: bold;
        }}
        .phase-icon.done {{ background: #00ff88; color: #0a0a0a; }}
        .phase-icon.current {{ background: #4ecdc4; color: #0a0a0a; animation: pulse 2s infinite; }}
        .phase-icon.todo {{ background: #333; color: #888; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} }}
        .phase-title {{ font-size: 1.1em; font-weight: bold; }}
        .phase-title .status {{
            font-size: 0.8em; padding: 3px 10px; border-radius: 4px;
            margin-left: 10px; vertical-align: middle;
        }}
        .status.done {{ background: #00ff8822; color: #00ff88; }}
        .status.current {{ background: #4ecdc422; color: #4ecdc4; }}
        .status.todo {{ background: #333; color: #888; }}
        .phase-description {{ color: #ccc; margin-bottom: 10px; font-size: 0.9em; line-height: 1.5; }}
        .phase-status {{ color: #888; font-size: 0.85em; margin-top: 5px; }}
        .progress-bar {{
            height: 4px; background: #333; border-radius: 2px; overflow: hidden; margin: 15px 0;
        }}
        .progress-fill {{ height: 100%; background: #4ecdc4; transition: width 0.5s ease; }}
        .progress-fill.done {{ background: #00ff88; }}
        .tasks {{ margin-left: 45px; font-size: 0.85em; color: #aaa; }}
        .tasks ul {{ list-style: none; padding-left: 0; }}
        .tasks li {{
            padding: 5px 0; border-bottom: 1px dashed #222;
        }}
        .tasks li:last-child {{ border-bottom: none; }}
        .tasks .check {{ color: #00ff88; margin-right: 8px; }}
        .tasks .pending {{ color: #555; margin-right: 8px; }}
        .highlight-box {{
            background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 20px; margin: 20px 0;
        }}
        .highlight-box h4 {{ color: #4ecdc4; margin-bottom: 10px; }}
        .highlight-box p {{ color: #ccc; line-height: 1.6; }}
        .timeline-bar {{
            display: flex; align-items: center; margin: 30px 0; padding: 20px; background: #1a1a2e; border-radius: 8px;
        }}
        .timeline-step {{
            flex: 1; text-align: center; padding: 10px; position: relative;
        }}
        .timeline-step:not(:last-child)::after {{
            content: ''; position: absolute; right: -50%; top: 50%;
            width: 100%; height: 2px; background: #333; z-index: 0;
        }}
        .timeline-step.active {{ color: #4ecdc4; font-weight: bold; }}
        .timeline-step .number {{
            display: inline-block; width: 24px; height: 24px; border-radius: 50%;
            background: #333; color: #888; line-height: 24px; font-size: 0.8em; margin-bottom: 5px;
        }}
        .timeline-step.active .number {{ background: #4ecdc4; color: #0a0a0a; }}
        .timeline-step .label {{ font-size: 0.85em; color: #aaa; }}
        .footer {{
            text-align: center; padding: 40px; color: #555; font-size: 0.85em;
            border-top: 1px solid #222; margin-top: 40px;
        }}
        .footer a {{ color: #4ecdc4; text-decoration: none; }}
        .footer a:hover {{ color: #00ff88; }}
        .update-timestamp {{
            text-align: center; color: #666; font-size: 0.8em; margin-top: 20px;
        }}
        .stat-cards {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0;
        }}
        .stat-card {{
            background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 20px; text-align: center;
        }}
        .stat-card .number {{ font-size: 2em; font-weight: bold; color: #4ecdc4; }}
        .stat-card .label {{ font-size: 0.85em; color: #888; margin-top: 5px; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="subtitle">RTA-GUARD</div>
        <h1>Mission Control</h1>
        <p class="tagline">Cosmic Order for AI — Progress Tracker</p>
        <span class="status-badge live">● LIVE</span>
    </div>

    <div class="container">
        <div class="section">
            <div class="section-title">Current Status</div>
            <div class="stat-cards">
                <div class="stat-card">
                    <div class="number">{current_phase}</div>
                    <div class="label">Current Phase</div>
                </div>
                <div class="stat-card">
                    <div class="number">{complete_phases}/7</div>
                    <div class="label">Phases Complete</div>
                </div>
                <div class="stat-card">
                    <div class="number">{completed_tasks}</div>
                    <div class="label">Key Milestones Done</div>
                </div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Mission Timeline</div>
            <div class="timeline-bar">
"""

    # Timeline steps
    for i in range(7):
        active_class = "active" if i <= current_phase else ""
        label = {
            0: "Kill-Switch<br>MVP",
            1: "RTA Rules<br>Engine",
            2: "Brahmanda<br>Map",
            3: "Conscience<br>Monitor",
            4: "Enterprise<br>Features",
            5: "Sudarshan<br>Wasm",
            6: "Ecosystem<br>& Scale"
        }[i]
        html += f"""
                <div class="timeline-step {active_class}" data-phase="{i}">
                    <div class="number">{i}</div>
                    <div class="label">{label}</div>
                </div>
"""

    html += f"""
            </div>
        </div>

        <div class="section">
            <div class="section-title">Phase Breakdown</div>
"""

    # Phase data
    phase_info = {
        0: {
            "title": "Phase 0 — Kill-Switch MVP",
            "desc": "Built the Sudarshan Firewall — a working session terminator with pattern-based detection, dashboard, LLM integration, and real-time monitoring.",
            "tasks": [
                "DiscusGuard core engine",
                "Pattern-based rule detection",
                "FastAPI dashboard with WebSocket",
                "Token-based authentication",
                "LLM providers (OpenAI, Anthropic, compatible)",
                "NeMo Guardrails integration",
                "Demo apps (CLI, real LLM, hybrid)",
                "Docker packaging",
                "Tests (11/11 passing)",
                "Showcase page published"
            ]
        },
        1: {
            "title": "Phase 1 — RTA Rules Engine",
            "desc": "Replace pattern-based rules with Vedic principle-based governance. Implement R1-R13 from the Rig Veda: Satya (Truth), Yama (Boundaries), Mitra (Trust), Agni (Transparency), Dharma (Duty), Varuna (Binding), Sarasvati (Knowledge Purity), Vayu (Health), Indra (Restraint), Drift Scoring, Maya Detection, Tamas Protocol.",
            "tasks": [
                "Research Vedic principles",
                "Codify 13 rules (R1-R13) in documentation",
                "Enhance with verse-level references (Claude Code)",
                "Implement RtaEngine (Python)",
                "An-Rta drift scoring system",
                "Rule priority & conflict resolution",
                "Temporal consistency check (R7)",
                "Hallucination scoring (R12)",
                "Health monitoring (R9)"
            ]
        },
        2: {
            "title": "Phase 2 — Brahmanda Map (Ground Truth)",
            "desc": "Build the ground truth database. AI must verify its 'thoughts' against verified reality before speaking. Anti-hallucination at the source.",
            "tasks": [
                "Design ground truth schema",
                "Knowledge base architecture (vector/graph DB)",
                "Truth verification pipeline",
                "Source attribution system",
                "Confidence scoring",
                "Knowledge base mutation tracking"
            ]
        },
        3: {
            "title": "Phase 3 — Conscience Monitor",
            "desc": "Persistent behavioral tracking over time. Measures drift, detects Tamas (darkness), maintains temporal consistency. The long-term watchfulness.",
            "tasks": [
                "Session behavioral profiling",
                "Live An-Rta drift scoring",
                "Tamas detection protocol",
                "Temporal consistency enforcement (R7)",
                "User behavior anomaly detection",
                "Escalation protocols (throttle → human → kill)"
            ]
        },
        4: {
            "title": "Phase 4 — Enterprise Features",
            "desc": "Make RTA-GUARD production-ready for enterprise: multi-tenant, RBAC, compliance reporting, webhooks, SSO, rate limiting, SLA monitoring.",
            "tasks": [
                "Multi-tenant isolation",
                "RBAC (admin, operator, viewer)",
                "Compliance reporting (EU AI Act, SOC2, HIPAA)",
                "Webhook notifications",
                "SSO integration (SAML, OIDC)",
                "API documentation (OpenAPI spec)",
                "Rate limiting & quotas",
                "SLA monitoring & uptime tracking"
            ]
        },
        5: {
            "title": "Phase 5 — Sudarshan Wasm Module",
            "desc": "Compile the kill-switch engine to WebAssembly. Embeddable anywhere: browser extensions, server middleware, CLI wrappers. Language-agnostic runtime.",
            "tasks": [
                "Rewrite core in Rust/C",
                "Wasm compilation pipeline",
                "Browser injection support",
                "WASI system integration",
                "Multi-language bindings (Python, JS, Go, etc.)",
                "Performance optimization"
            ]
        },
        6: {
            "title": "Phase 6 — Ecosystem & Scale",
            "desc": "Open-source the core, build plugin system, integrations with major AI frameworks (NeMo, Bedrock, LangChain), community rule marketplace, full documentation.",
            "tasks": [
                "Open-source release (Apache 2.0)",
                "Plugin architecture",
                "Framework integrations (NeMo, Bedrock, LangChain)",
                "Rule marketplace",
                "Industry-specific rule packs",
                "Full documentation site",
                "CI/CD integration (GitHub Actions)",
                "Community governance"
            ]
        }
    }

    for phase_num in range(7):
        status = phases[phase_num]["status"]
        info = phase_info[phase_num]
        phase_title = info["title"]
        phase_desc = info["desc"]
        tasks = info["tasks"]

        # Determine status class and text
        if status == "done":
            status_class = "done"
            status_text = "COMPLETE"
            icon = "✓"
            progress_width = "100%"
        elif status == "current":
            status_class = "current"
            status_text = "IN PROGRESS"
            icon = "●"
            progress_width = "20%"  # Could calculate based on tasks done
        else:
            status_class = "todo"
            status_text = "NOT STARTED"
            icon = "○"
            progress_width = "0%"

        # Calculate which tasks are done based on file existence (simplified)
        done_tasks = []
        # This is a simplified mapping — in reality we'd track this properly
        if phase_num == 0:
            done_tasks = [True] * len(tasks)  # All done
        elif phase_num == 1:
            done_tasks = [
                True,  # Research
                True,  # Codify
                False,  # Verse references
                (ROOT / "discus/rta_engine.py").exists(),
                False, False, False, False, False, False, False, False
            ][:len(tasks)]
        else:
            done_tasks = [False] * len(tasks)

        html += f"""
            <!-- Phase {phase_num} -->
            <div class="phase" data-phase="{phase_num}">
                <div class="phase-header">
                    <div class="phase-icon {status_class}">{icon}</div>
                    <div class="phase-title">{phase_title} <span class="status {status_class}">{status_text}</span></div>
                </div>
                <div class="phase-description">{phase_desc}</div>
                <div class="progress-bar"><div class="progress-fill {status_class}" style="width: {progress_width}"></div></div>
                <div class="phase-status">
                    {"✅ All tasks complete" if status == "done" else "🔄 " + ("RTA Ruleset documented | Saurabh enhancing with Claude Code | RtaEngine implementation starting" if phase_num == 1 else "Not started — blocked on earlier phases")}
                </div>
                <div class="tasks">
                    <ul>
"""

        for i, task in enumerate(tasks):
            check = "✓" if done_tasks[i] else "○"
            check_class = "check" if done_tasks[i] else "pending"
            html += f'                        <li><span class="{check_class}">{check}</span>{task}</li>\n'

        html += f"""
                    </ul>
                </div>
            </div>
"""

    html += f"""
        </div>

        <div class="section">
            <div class="section-title">What's Happening Now</div>
            <div class="highlight-box">
                <h4>🎯 Current Mission: Phase 1 — RTA Rules Engine</h4>
                <p>
                    <strong>What:</strong> Codifying the 13 Vedic laws (R1-R13) into Python code.<br>
                    <strong>Blocking:</strong> Awaiting enhanced ruleset from Claude Code research.<br>
                    <strong>Next:</strong> Once we have the finalized rules, we'll implement <code>RtaEngine</code> that replaces the pattern-based detection with principle-based governance.
                </p>
            </div>
            <div class="highlight-box">
                <h4>📊 Real-Time Dashboard</h4>
                <p>
                    The technical dashboard (localhost:8000) shows live kills, warnings, and passes. The Mission Control page you're viewing now is the <em>public progress tracker</em> — updated after each commit.
                </p>
            </div>
        </div>

        <div class="update-timestamp">
            Last updated: <span id="last-updated">{timestamp}</span><br>
            Repository: <a href="https://github.com/ashish797/RTA-GUARD" target="_blank">github.com/ashish797/RTA-GUARD</a> (pending push)<br>
            Generated by: update_mission_control.py
        </div>

        <div class="footer">
            RTA-GUARD — The Seatbelt for AI<br>
            "NeMo guards the prompts. RTA-GUARD kills the session."
        </div>
    </div>

    <script>
        // Timeline highlight for current phase
        const currentPhase = {current_phase};
        document.querySelectorAll('.timeline-step').forEach((step, idx) => {{
            if (idx < currentPhase) {{
                step.classList.add('active');
                step.querySelector('.number').style.background = '#00ff88';
                step.querySelector('.number').style.color = '#0a0a0a';
            }}
        }});
        document.getElementById('phase-num').textContent = currentPhase;
        document.getElementById('complete-phases').textContent = '{complete_phases}/7';
        document.getElementById('total-tasks-complete').textContent = '{completed_tasks}';
    </script>
</body>
</html>"""

    # Write the file
    output_path = ROOT / "mission-control" / "index.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    print(f"✓ Mission Control updated: {output_path}")
    return output_path


if __name__ == "__main__":
    phases = parse_phase_status()
    completed = count_completed_tasks()
    generate_html(phases, completed)
    print("✅ Mission Control up to date")
