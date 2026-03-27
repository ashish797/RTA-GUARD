"""Financial Fraud Detection Plugin"""
import re
from discus.plugins import PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity


class Plugin(PluginBase):
    fraud_phrases = [
        r"wire\s+transfer\s+to\s+(?:offshore|overseas|international)",
        r"bypass\s+(?:verification|authentication|security)",
        r"fake\s+(?:invoice|receipt|statement)",
        r"launder(?:ing)?\s+money",
        r"account\s+enumeration",
        r"card\s+(?:testing|cracking|stuffing)",
        r"social\s+engineering\s+(?:attack|scam)",
        r"phishing\s+(?:scheme|attempt|campaign)",
    ]
    patterns = [re.compile(p, re.IGNORECASE) for p in fraud_phrases]

    suspicious_amounts = re.compile(
        r"\$\s*[\d,]{6,}(?:\.\d{2})?",  # $100,000+
    )

    account_enumeration = re.compile(
        r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"  # Credit card pattern
    )

    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        text = context.input_text if hook == PluginHook.ON_INPUT else context.output_text
        flags = []

        # Check fraud phrases
        for i, pattern in enumerate(self.patterns):
            if pattern.search(text):
                flags.append({"type": "fraud_phrase", "pattern": self.fraud_phrases[i][:40]})

        # Check large amounts
        amounts = self.suspicious_amounts.findall(text)
        if amounts:
            flags.append({"type": "large_amount", "values": amounts[:3]})

        # Check card number patterns
        cards = self.account_enumeration.findall(text)
        if cards:
            flags.append({"type": "card_pattern", "count": len(cards)})

        if flags:
            severity = PluginSeverity.KILL if any(f["type"] == "card_pattern" for f in flags) else PluginSeverity.WARN
            return PluginResult(
                plugin_id=self.plugin_id,
                hook=hook,
                violated=True,
                severity=severity,
                message=f"Financial fraud indicators: {len(flags)} detected",
                details={"flags": flags},
                score=min(1.0, len(flags) * 0.35),
            )

        return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False, message="Clean")
