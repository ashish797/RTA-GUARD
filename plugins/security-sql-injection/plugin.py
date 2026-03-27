"""SQL Injection Detector Plugin"""
import re
from discus.plugins import PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity


class Plugin(PluginBase):
    sql_patterns = [
        (re.compile(r"\b(?:DROP|DELETE|TRUNCATE)\s+(?:TABLE|FROM|DATABASE)\b", re.IGNORECASE), "destructive_sql"),
        (re.compile(r"\bUNION\s+(?:ALL\s+)?SELECT\b", re.IGNORECASE), "union_select"),
        (re.compile(r"(?:'|\")\s*(?:OR|AND)\s+(?:'|\")?\s*=?\s*(?:'|\")?", re.IGNORECASE), "tautology"),
        (re.compile(r";\s*(?:DROP|DELETE|INSERT|UPDATE|ALTER|CREATE)\b", re.IGNORECASE), "statement_injection"),
        (re.compile(r"\bSLEEP\s*\(\s*\d+\s*\)", re.IGNORECASE), "time_based_blind"),
        (re.compile(r"\bBENCHMARK\s*\(", re.IGNORECASE), "benchmark_attack"),
        (re.compile(r"(?:--|#|/\*)\s*(?:DROP|DELETE|SELECT)", re.IGNORECASE), "comment_injection"),
        (re.compile(r"\b(?:xp_cmdshell|xp_regread|xp_filelist)\b", re.IGNORECASE), "mssql_xp"),
        (re.compile(r"\bLOAD_FILE\s*\(|INTO\s+(?:OUT|DUMP)FILE\b", re.IGNORECASE), "file_operation"),
        (re.compile(r"0x[0-9a-fA-F]{4,}", re.IGNORECASE), "hex_encoded"),
    ]

    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        text = context.input_text
        detections = []

        for pattern, name in self.sql_patterns:
            if pattern.search(text):
                detections.append(name)

        if detections:
            return PluginResult(
                plugin_id=self.plugin_id,
                hook=hook,
                violated=True,
                severity=PluginSeverity.KILL,
                message=f"SQL injection detected: {', '.join(detections)}",
                details={"patterns": detections},
                score=min(1.0, len(detections) * 0.3),
            )

        return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False, message="No SQL injection")
