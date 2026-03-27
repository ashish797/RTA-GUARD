"""Secrets & Credentials Scanner Plugin"""
import re
from discus.plugins import PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity


class Plugin(PluginBase):
    patterns = {
        "aws_key": re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        "github_token": re.compile(r"\b(ghp_[a-zA-Z0-9]{36})\b"),
        "slack_token": re.compile(r"\b(xox[bporas]-[a-zA-Z0-9-]{10,})\b"),
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
        "jwt_token": re.compile(r"\b(eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})\b"),
        "generic_api_key": re.compile(r"(?:api[_-]?key|apikey|secret)[\"':=\s]+[\"']?([a-zA-Z0-9_\-]{20,})[\"']?", re.IGNORECASE),
        "password_field": re.compile(r"(?:password|passwd|pwd)[\"':=\s]+[\"']?([^\s\"'}]{6,})[\"']?", re.IGNORECASE),
        "connection_string": re.compile(r"(?:mysql|postgres|mongodb|redis)://[^\s\"']+", re.IGNORECASE),
        "bearer_token": re.compile(r"Bearer\s+([a-zA-Z0-9_\-\.]{20,})", re.IGNORECASE),
    }

    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        text = context.input_text if hook == PluginHook.ON_INPUT else context.output_text
        findings = []

        for name, pattern in self.patterns.items():
            matches = pattern.findall(text)
            if matches:
                findings.append({"type": name, "count": len(matches)})

        if findings:
            return PluginResult(
                plugin_id=self.plugin_id,
                hook=hook,
                violated=True,
                severity=PluginSeverity.KILL,
                message=f"Secrets detected: {', '.join(f['type'] for f in findings)}",
                details={"findings": findings},
                score=0.95,
            )

        return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False, message="No secrets found")
