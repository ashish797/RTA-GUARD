# RTA-GUARD — Logging & ELK Stack

Phase 6.3 — Structured logging with Elasticsearch, Logstash, Kibana (ELK) integration.

## Overview

RTA-GUARD emits structured JSON logs for every guard check, kill decision, rule violation, and system event. These logs are ingested by an ELK stack for search, visualization, and alerting.

## Log Format

Every log line is a single JSON object with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 | UTC timestamp of the event |
| `level` | string | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `message` | string | Human-readable log message |
| `module` | string | Python module name |
| `function` | string | Function name where log was emitted |
| `line` | integer | Source file line number |
| `service` | string | Always `"rta-guard"` |
| `hostname` | string | Container/host identifier |
| `logger` | string | Python logger name |
| `request_id` | string | HTTP request correlation ID (when available) |
| `session_id` | string | RTA-GUARD session being evaluated |
| `agent_id` | string | AI agent identifier |
| `correlation_id` | string | Cross-module trace ID for kill decisions |

### Event-Specific Fields

Kill decisions include additional fields:
```json
{
  "event_type": "kill_decision",
  "rule_id": "R3_MITRA",
  "severity": "critical",
  "reason": "PII detected: email address",
  "session_id": "sess_abc123",
  "agent_id": "agent_gpt4"
}
```

Guard checks include:
```json
{
  "event_type": "guard_check",
  "session_id": "sess_abc123",
  "result": "pass|warn|kill",
  "duration_ms": 2.35
}
```

Rule violations include:
```json
{
  "event_type": "rule_violation",
  "rule_id": "R12_MAYA",
  "severity": "high",
  "session_id": "sess_abc123",
  "message": "Hallucination confidence below threshold"
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `WARNING` | Minimum log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `LOG_FORMAT` | `json` | Output format: `json` (ELK) or `plain` (human-readable) |
| `LOG_FILE` | `logs/rta-guard.log` | Log file path |
| `LOG_DIR` | `logs` | Log directory (created automatically) |
| `LOG_MAX_BYTES` | `10485760` (10MB) | Max log file size before rotation |
| `LOG_BACKUP_COUNT` | `5` | Number of rotated backup files |
| `LOG_TO_CONSOLE` | `true` | Log to stdout |
| `LOG_TO_FILE` | `true` | Log to file |

### Python Usage

```python
from brahmanda.logging_config import (
    configure_logging,
    get_logger,
    set_request_context,
    new_correlation_id,
    log_kill_decision,
    log_violation,
    log_check,
)

# At startup
configure_logging()

# Get a logger
logger = get_logger("brahmanda.guard")

# Set request context (persists across calls in same thread)
set_request_context(
    request_id="req_abc123",
    session_id="sess_xyz789",
    agent_id="agent_gpt4",
)
correlation_id = new_correlation_id()

# Log structured events
log_kill_decision(logger, session_id="sess_xyz789", agent_id="agent_gpt4",
                  reason="PII detected", rule_id="R3_MITRA", severity="critical")

log_violation(logger, session_id="sess_xyz789", rule_id="R12_MAYA",
              severity="high", message="Hallucination detected")

log_check(logger, session_id="sess_xyz789", result="pass", duration_ms=2.35)

# Clear context when request completes
clear_request_context()
```

## ELK Stack Setup

### Quick Start

```bash
# Start the full stack (includes ELK)
docker compose up -d

# Verify services
docker compose ps
curl http://localhost:9200/_cluster/health   # Elasticsearch
curl http://localhost:5601/api/status         # Kibana
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| Elasticsearch | 9200 | Log storage and search |
| Logstash | 5044 (beats), 5000 (TCP/JSON) | Log ingestion pipeline |
| Kibana | 5601 | Log visualization and dashboards |

### Architecture

```
RTA-GUARD App → JSON logs → file → Filebeat → Logstash → Elasticsearch → Kibana
                (or TCP)  → ─────────→ Logstash ─────→
```

### Logstash Pipeline

The Logstash pipeline (`logging/logstash.conf`) handles:
1. **Input**: Receives logs via Beats (port 5044) or direct TCP/JSON (port 5000)
2. **Filter**: Parses JSON, converts timestamps, enriches with severity levels, tags kill decisions
3. **Output**: Writes to Elasticsearch index `rta-guard-logs-YYYY.MM.dd`

## Importing the Kibana Dashboard

1. Open Kibana at `http://localhost:5601`
2. Navigate to **Stack Management → Saved Objects**
3. Click **Import** and upload `logging/kibana/dashboard.ndjson`
4. Select the `rta-guard-logs-*` index pattern when prompted

### Dashboard Panels

| Panel | Type | Description |
|-------|------|-------------|
| Kill Decisions Over Time | Area chart | Session kills aggregated by hour |
| Top Rules Triggered | Pie chart | Most frequently triggered kill rules |
| Agent Activity | Stacked bar | Events per agent over time |
| Error & Critical Rates | Line chart | ERROR/CRITICAL entries by level |
| Log Level Breakdown | Pie chart | Distribution of log levels |
| Guard Check Latency | Histogram | Check duration distribution (ms) |
| Kill Severity Breakdown | Metric | Total kill decision count |
| Top Exception Types | Horizontal bar | Most common exceptions |
| Kill Decision Trace | Saved search | Searchable kill events with correlation IDs |

## Kibana Query Examples

### Find all kills for a specific session
```
event_type:kill_decision AND session_id:"sess_abc123"
```

### Find kills by a specific rule in the last hour
```
event_type:kill_decision AND rule_id:"R3_MITRA" AND @timestamp >= now-1h
```

### Find all errors for a specific agent
```
level:ERROR AND agent_id:"agent_gpt4"
```

### Trace a kill decision by correlation ID
```
correlation_id:"a1b2c3d4e5f6"
```

### Find high-latency guard checks
```
event_type:guard_check AND duration_ms > 100
```

### Find PII-related kills
```
event_type:kill_decision AND message:*PII*
```

### Count kills per rule (last 24h)
```
event_type:kill_decision AND @timestamp >= now-24h
```
→ Use the **Top Rules Triggered** visualization, or run in **Discover** with a terms aggregation on `rule_id`.

### Find sessions killed by multiple rules
```
event_type:kill_decision
```
→ In **Discover**, group by `session_id` and look for counts > 1.

### Monitor error rate trends
```
level:(ERROR OR CRITICAL) AND @timestamp >= now-6h
```
→ Use the **Error & Critical Rates** visualization.

## Log Analysis (Python)

The `brahmanda/log_analyzer` module provides offline log analysis:

```python
from brahmanda.log_analyzer import (
    parse_log_file, parse_log_directory,
    aggregate_kills, detect_anomalies, generate_daily_summary,
    summary_to_dict,
)

# Parse logs
entries = parse_log_file("logs/rta-guard.log")
# or
entries = parse_log_directory("logs/")

# Aggregate kills
kills = aggregate_kills(entries)
print(f"Total kills: {kills.total_kills}")
print(f"By rule: {kills.by_rule}")

# Detect anomalies
anomalies = detect_anomalies(entries, window_minutes=15, z_threshold=2.5)
for a in anomalies:
    print(f"ANOMALY: {a.description}")

# Daily summary
summary = generate_daily_summary(entries)
result = summary_to_dict(summary)
```

### CLI Usage

```bash
# Analyze a log file
python -m brahmanda.log_analyzer logs/rta-guard.log

# Analyze a specific date
python -m brahmanda.log_analyzer logs/ --date 2026-03-26

# Output is JSON (pipe to jq for formatting)
python -m brahmanda.log_analyzer logs/rta-guard.log | jq .
```

### Anomaly Detection

The analyzer uses statistical spike detection:
- Sliding window (default: 15 minutes)
- Flags windows where kill count exceeds `mean + 2.5 * stdev`
- Critical anomaly at `mean + 3 * stdev`
- Requires at least 4 windows for statistical significance

## Log Rotation

Log files are automatically rotated by Python's `RotatingFileHandler`:
- **Max size**: 10MB per file (configurable via `LOG_MAX_BYTES`)
- **Backup count**: 5 files (configurable via `LOG_BACKUP_COUNT`)
- **Naming**: `rta-guard.log`, `rta-guard.log.1`, ..., `rta-guard.log.5`
- Oldest file is deleted when rotation exceeds backup count

## Production Considerations

### Elasticsearch
- Increase `discovery.type` from `single-node` to a proper cluster in production
- Enable `xpack.security.enabled` with TLS
- Set retention policies via ILM (Index Lifecycle Management)
- Monitor disk usage — logs grow fast at DEBUG level

### Logstash
- Tune `pipeline.workers` and `pipeline.batch.size` for your load
- Add dead-letter queue for failed events
- Use persistent queues for reliability

### Kibana
- Enable authentication (`xpack.security.enabled`)
- Set up role-based access control
- Create alerting rules for anomaly thresholds

### Logging
- Keep `LOG_LEVEL=WARNING` in production (DEBUG is very verbose)
- Use `LOG_FORMAT=json` for ELK ingestion
- Forward logs to a central log aggregator for multi-node deployments
- Consider adding a Filebeat sidecar for containerized deployments

## Files

```
brahmanda/
  logging_config.py    # Structured logging configuration + formatters
  log_analyzer.py      # Log parsing, aggregation, anomaly detection

logging/
  elasticsearch.yml    # ES single-node dev config
  logstash.conf        # Logstash pipeline (input → filter → output)
  kibana.yml           # Kibana dev config
  pipeline.yml         # Logstash pipeline registry
  kibana/
    dashboard.ndjson   # Importable Kibana dashboard (9 panels)
```
