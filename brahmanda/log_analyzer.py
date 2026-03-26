"""
RTA-GUARD — Log Analyzer (Phase 6.3)

Parse JSON-structured logs for pattern detection, anomaly detection,
and daily summary generation. Designed for RTA-GUARD's structured log format.

Features:
    - Parse JSON log files line-by-line
    - Aggregate kill decisions by rule, time window, agent
    - Detect anomalies in kill rates (statistical spike detection)
    - Generate daily log summaries with key metrics
"""
import json
import os
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─── Data classes ─────────────────────────────────────────────────

@dataclass
class LogEntry:
    """Parsed structured log entry."""
    timestamp: datetime
    level: str
    message: str
    module: str
    function: str
    line: int
    service: str = "rta-guard"
    hostname: str = ""
    logger: str = ""
    request_id: str = ""
    session_id: str = ""
    agent_id: str = ""
    correlation_id: str = ""
    event_type: str = ""
    rule_id: str = ""
    severity: str = ""
    result: str = ""
    duration_ms: float = 0.0
    exception: str = ""
    exception_type: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KillAggregate:
    """Aggregated kill statistics."""
    total_kills: int = 0
    by_rule: Dict[str, int] = field(default_factory=dict)
    by_agent: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_hour: Dict[int, int] = field(default_factory=dict)
    by_session: Dict[str, int] = field(default_factory=dict)
    avg_checks_per_kill: float = 0.0


@dataclass
class AnomalyReport:
    """Detected anomaly in kill rates."""
    timestamp: datetime
    window_start: datetime
    window_end: datetime
    kill_count: int
    expected_max: float
    severity: str  # "warning" or "critical"
    description: str


@dataclass
class DailySummary:
    """Daily log summary."""
    date: str
    total_log_entries: int = 0
    by_level: Dict[str, int] = field(default_factory=dict)
    kill_aggregate: KillAggregate = field(default_factory=KillAggregate)
    top_rules: List[Tuple[str, int]] = field(default_factory=list)
    top_agents: List[Tuple[str, int]] = field(default_factory=list)
    error_count: int = 0
    critical_count: int = 0
    exceptions: Dict[str, int] = field(default_factory=dict)
    anomalies: List[AnomalyReport] = field(default_factory=list)
    check_results: Dict[str, int] = field(default_factory=dict)
    avg_check_duration_ms: float = 0.0
    unique_sessions: int = 0
    unique_agents: int = 0
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None


# ─── Log parser ───────────────────────────────────────────────────

def parse_log_line(line: str) -> Optional[LogEntry]:
    """Parse a single JSON log line into a LogEntry.

    Returns None if the line is not valid JSON or not a log entry.
    """
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    # Parse timestamp
    ts_str = data.get("timestamp", "")
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts = datetime.now(tz=timezone.utc)

    return LogEntry(
        timestamp=ts,
        level=data.get("level", "UNKNOWN"),
        message=data.get("message", ""),
        module=data.get("module", ""),
        function=data.get("function", ""),
        line=data.get("line", 0),
        service=data.get("service", ""),
        hostname=data.get("hostname", ""),
        logger=data.get("logger", ""),
        request_id=data.get("request_id", ""),
        session_id=data.get("session_id", ""),
        agent_id=data.get("agent_id", ""),
        correlation_id=data.get("correlation_id", ""),
        event_type=data.get("event_type", ""),
        rule_id=data.get("rule_id", ""),
        severity=data.get("severity", ""),
        result=data.get("result", ""),
        duration_ms=data.get("duration_ms", 0.0),
        exception=data.get("exception", ""),
        exception_type=data.get("exception_type", ""),
        raw=data,
    )


def parse_log_file(filepath: str) -> List[LogEntry]:
    """Parse an entire JSON log file.

    Args:
        filepath: Path to the log file

    Returns:
        List of parsed LogEntry objects
    """
    entries = []
    path = Path(filepath)
    if not path.exists():
        return entries

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            entry = parse_log_line(line)
            if entry:
                entries.append(entry)

    return entries


def parse_log_directory(dirpath: str, pattern: str = "*.log") -> List[LogEntry]:
    """Parse all log files in a directory.

    Args:
        dirpath: Directory containing log files
        pattern: Glob pattern for log files

    Returns:
        Sorted list of all parsed entries (by timestamp)
    """
    entries = []
    path = Path(dirpath)
    if not path.is_dir():
        return entries

    for log_file in sorted(path.glob(pattern)):
        entries.extend(parse_log_file(str(log_file)))

    entries.sort(key=lambda e: e.timestamp)
    return entries


# ─── Kill aggregation ─────────────────────────────────────────────

def aggregate_kills(
    entries: List[LogEntry],
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> KillAggregate:
    """Aggregate kill decisions from log entries.

    Args:
        entries: Parsed log entries
        start_time: Optional filter start (inclusive)
        end_time: Optional filter end (inclusive)

    Returns:
        KillAggregate with counts by rule, agent, severity, hour
    """
    agg = KillAggregate()
    check_count = 0

    for entry in entries:
        # Filter by time range
        if start_time and entry.timestamp < start_time:
            continue
        if end_time and entry.timestamp > end_time:
            continue

        # Count kills
        if entry.event_type == "kill_decision":
            agg.total_kills += 1

            if entry.rule_id:
                agg.by_rule[entry.rule_id] = agg.by_rule.get(entry.rule_id, 0) + 1
            if entry.agent_id:
                agg.by_agent[entry.agent_id] = agg.by_agent.get(entry.agent_id, 0) + 1
            if entry.severity:
                agg.by_severity[entry.severity] = agg.by_severity.get(entry.severity, 0) + 1
            if entry.session_id:
                agg.by_session[entry.session_id] = agg.by_session.get(entry.session_id, 0) + 1

            hour = entry.timestamp.hour
            agg.by_hour[hour] = agg.by_hour.get(hour, 0) + 1

        # Count checks for ratio
        if entry.event_type == "guard_check":
            check_count += 1

    # Average checks per kill
    if agg.total_kills > 0 and check_count > 0:
        agg.avg_checks_per_kill = round(check_count / agg.total_kills, 2)

    return agg


# ─── Anomaly detection ────────────────────────────────────────────

def detect_anomalies(
    entries: List[LogEntry],
    window_minutes: int = 15,
    z_threshold: float = 2.5,
    min_windows: int = 4,
) -> List[AnomalyReport]:
    """Detect anomalous spikes in kill rates.

    Uses a sliding window approach: computes kill counts per window,
    then flags windows that exceed mean + z_threshold * stddev.

    Args:
        entries: Parsed log entries
        window_minutes: Size of each analysis window in minutes
        z_threshold: Number of standard deviations for anomaly flag
        min_windows: Minimum windows needed for statistical analysis

    Returns:
        List of AnomalyReport objects for detected anomalies
    """
    if not entries:
        return []

    # Filter kill events
    kills = [e for e in entries if e.event_type == "kill_decision"]
    if not kills:
        return []

    # Sort by time
    kills.sort(key=lambda e: e.timestamp)

    # Determine time range
    start = kills[0].timestamp.replace(minute=0, second=0, microsecond=0)
    end = kills[-1].timestamp + timedelta(minutes=window_minutes)

    # Count kills per window
    window_delta = timedelta(minutes=window_minutes)
    window_counts: Dict[datetime, int] = {}

    current = start
    while current < end:
        window_end = current + window_delta
        count = sum(
            1 for k in kills
            if current <= k.timestamp < window_end
        )
        if count > 0:
            window_counts[current] = count
        current = window_end

    if len(window_counts) < min_windows:
        return []

    # Statistical analysis
    counts = list(window_counts.values())
    mean_count = statistics.mean(counts)
    try:
        stdev_count = statistics.stdev(counts)
    except statistics.StatisticsError:
        stdev_count = 0

    if stdev_count == 0:
        return []

    # Detect anomalies
    anomalies = []
    threshold = mean_count + z_threshold * stdev_count

    for window_start, count in window_counts.items():
        if count > threshold:
            severity = "critical" if count > mean_count + 3 * stdev_count else "warning"
            anomalies.append(AnomalyReport(
                timestamp=window_start,
                window_start=window_start,
                window_end=window_start + window_delta,
                kill_count=count,
                expected_max=round(threshold, 2),
                severity=severity,
                description=(
                    f"Kill rate spike: {count} kills in {window_minutes}min window "
                    f"(expected max: {threshold:.1f}, mean: {mean_count:.1f}, "
                    f"stdev: {stdev_count:.1f})"
                ),
            ))

    return anomalies


# ─── Daily summary ────────────────────────────────────────────────

def generate_daily_summary(
    entries: List[LogEntry],
    date: Optional[str] = None,
) -> DailySummary:
    """Generate a daily summary from log entries.

    Args:
        entries: Parsed log entries (should be for a single day)
        date: Date string YYYY-MM-DD (auto-detected from entries if None)

    Returns:
        DailySummary with aggregated statistics
    """
    if not entries:
        return DailySummary(date=date or "unknown")

    # Auto-detect date
    if date is None:
        date = entries[0].timestamp.strftime("%Y-%m-%d")

    summary = DailySummary(date=date)
    summary.total_log_entries = len(entries)

    # Level counts
    level_counts: Dict[str, int] = Counter()
    exception_counts: Dict[str, int] = Counter()
    check_durations: List[float] = []
    check_results: Dict[str, int] = Counter()
    sessions: set = set()
    agents: set = set()

    for entry in entries:
        level_counts[entry.level] += 1

        if entry.level == "ERROR":
            summary.error_count += 1
        if entry.level == "CRITICAL":
            summary.critical_count += 1

        if entry.exception_type:
            exception_counts[entry.exception_type] += 1

        if entry.event_type == "guard_check":
            check_results[entry.result] = check_results.get(entry.result, 0) + 1
            if entry.duration_ms > 0:
                check_durations.append(entry.duration_ms)

        if entry.session_id:
            sessions.add(entry.session_id)
        if entry.agent_id:
            agents.add(entry.agent_id)

        # Time range
        ts_str = entry.timestamp.isoformat()
        if summary.time_range_start is None or ts_str < summary.time_range_start:
            summary.time_range_start = ts_str
        if summary.time_range_end is None or ts_str > summary.time_range_end:
            summary.time_range_end = ts_str

    summary.by_level = dict(level_counts)
    summary.exceptions = dict(exception_counts)
    summary.check_results = dict(check_results)
    summary.unique_sessions = len(sessions)
    summary.unique_agents = len(agents)

    if check_durations:
        summary.avg_check_duration_ms = round(statistics.mean(check_durations), 2)

    # Kill aggregation
    summary.kill_aggregate = aggregate_kills(entries)

    # Top rules and agents
    summary.top_rules = sorted(
        summary.kill_aggregate.by_rule.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:10]
    summary.top_agents = sorted(
        summary.kill_aggregate.by_agent.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    # Anomaly detection
    summary.anomalies = detect_anomalies(entries)

    return summary


def summary_to_dict(summary: DailySummary) -> Dict[str, Any]:
    """Convert DailySummary to a JSON-serializable dict."""
    return {
        "date": summary.date,
        "total_log_entries": summary.total_log_entries,
        "by_level": summary.by_level,
        "kills": {
            "total": summary.kill_aggregate.total_kills,
            "by_rule": summary.kill_aggregate.by_rule,
            "by_agent": summary.kill_aggregate.by_agent,
            "by_severity": summary.kill_aggregate.by_severity,
            "by_hour": summary.kill_aggregate.by_hour,
            "avg_checks_per_kill": summary.kill_aggregate.avg_checks_per_kill,
        },
        "top_rules": summary.top_rules,
        "top_agents": summary.top_agents,
        "error_count": summary.error_count,
        "critical_count": summary.critical_count,
        "exceptions": summary.exceptions,
        "anomalies": [
            {
                "window_start": a.window_start.isoformat(),
                "window_end": a.window_end.isoformat(),
                "kill_count": a.kill_count,
                "expected_max": a.expected_max,
                "severity": a.severity,
                "description": a.description,
            }
            for a in summary.anomalies
        ],
        "checks": {
            "results": summary.check_results,
            "avg_duration_ms": summary.avg_check_duration_ms,
        },
        "unique_sessions": summary.unique_sessions,
        "unique_agents": summary.unique_agents,
        "time_range": {
            "start": summary.time_range_start,
            "end": summary.time_range_end,
        },
    }


# ─── CLI entry point ─────────────────────────────────────────────

def main():
    """CLI for log analysis. Usage: python -m brahmanda.log_analyzer <log_file_or_dir>"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m brahmanda.log_analyzer <log_file_or_dir> [--date YYYY-MM-DD]")
        sys.exit(1)

    target = sys.argv[1]
    date_filter = None

    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            date_filter = sys.argv[idx + 1]

    # Parse logs
    if os.path.isdir(target):
        entries = parse_log_directory(target)
    else:
        entries = parse_log_file(target)

    if not entries:
        print(f"No log entries found in {target}")
        sys.exit(0)

    # Filter by date if specified
    if date_filter:
        entries = [
            e for e in entries
            if e.timestamp.strftime("%Y-%m-%d") == date_filter
        ]

    # Generate summary
    summary = generate_daily_summary(entries, date=date_filter)
    result = summary_to_dict(summary)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
