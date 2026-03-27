"""Legal Disclaimer Checker Plugin"""
import re
from discus.plugins import PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity


class Plugin(PluginBase):
    advice_triggers = {
        "legal": [
            re.compile(r"\b(?:you should|I recommend|I advise)\s+(?:sue|file|litigate|lawyer|attorney|legal action)", re.IGNORECASE),
            re.compile(r"\blegal\s+(?:advice|counsel|opinion)\b", re.IGNORECASE),
            re.compile(r"\bstatute\s+of\s+limitations\b", re.IGNORECASE),
        ],
        "medical": [
            re.compile(r"\byou should\s+(?:take|stop|increase|decrease)\s+(?:your\s+)?(?:medication|dose|prescription)", re.IGNORECASE),
            re.compile(r"\bdiagnos(?:e|is)\s+(?:you|your)\s+(?:with|as)\b", re.IGNORECASE),
        ],
        "financial": [
            re.compile(r"\b(?:you should|I recommend)\s+(?:invest|buy|sell|trade)\b", re.IGNORECASE),
            re.compile(r"\bfinancial\s+(?:advice|recommendation|plan)\b", re.IGNORECASE),
        ],
    }

    disclaimer_patterns = {
        "legal": re.compile(r"(?:not\s+legal\s+advice|consult\s+(?:a\s+)?(?:lawyer|attorney))", re.IGNORECASE),
        "medical": re.compile(r"(?:not\s+medical\s+advice|consult\s+(?:a\s+)?(?:doctor|physician))", re.IGNORECASE),
        "financial": re.compile(r"(?:not\s+financial\s+advice|consult\s+(?:a\s+)?(?:financial\s+)?(?:advisor|planner))", re.IGNORECASE),
    }

    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        if hook != PluginHook.ON_OUTPUT:
            return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False)

        text = context.output_text
        missing = []

        for domain, triggers in self.advice_triggers.items():
            triggered = any(p.search(text) for p in triggers)
            if triggered:
                dp = self.disclaimer_patterns.get(domain)
                has_disclaimer = dp.search(text) if dp else False
                if not has_disclaimer:
                    missing.append(domain)

        if missing:
            return PluginResult(
                plugin_id=self.plugin_id,
                hook=hook,
                violated=True,
                severity=PluginSeverity.WARN,
                message=f"Missing disclaimers for: {', '.join(missing)} advice",
                details={"missing_disclaimers": missing},
                score=0.6,
            )

        return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False, message="Disclaimers OK")
