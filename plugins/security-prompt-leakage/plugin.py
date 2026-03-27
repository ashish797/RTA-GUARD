"""System Prompt Leakage Prevention Plugin"""
import re
from discus.plugins import PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity


class Plugin(PluginBase):
    leakage_patterns = [
        (re.compile(r"(?:my|the|your)\s+(?:system\s+)?(?:prompt|instructions?)\s+(?:is|are|says?|reads?)\s*:", re.IGNORECASE), "prompt_reveal"),
        (re.compile(r"I\s+(?:was|am)\s+(?:instructed|told|programmed|designed)\s+to\b", re.IGNORECASE), "instruction_reveal"),
        (re.compile(r"(?:here'?s?|these\s+are)\s+(?:my|the)\s+(?:rules?|guidelines?|instructions?|system\s+prompt)", re.IGNORECASE), "rules_reveal"),
        (re.compile(r"(?:begin|start)\s+(?:of\s+)?(?:system|internal)\s+(?:prompt|message|instructions?)", re.IGNORECASE), "boundary_leak"),
        (re.compile(r"<\|(?:im_start|system|assistant)\|>", re.IGNORECASE), "token_leak"),
        (re.compile(r"(?:role|content)\s*:\s*(?:system|assistant)\s*\n", re.IGNORECASE), "role_leak"),
        (re.compile(r"the\s+(?:first|initial|original)\s+message\s+(?:I\s+received|was)", re.IGNORECASE), "initial_message"),
    ]

    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        if hook != PluginHook.ON_OUTPUT:
            return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False)

        text = context.output_text
        detections = []

        for pattern, name in self.leakage_patterns:
            if pattern.search(text):
                detections.append(name)

        if detections:
            return PluginResult(
                plugin_id=self.plugin_id,
                hook=hook,
                violated=True,
                severity=PluginSeverity.KILL,
                message=f"System prompt leakage detected: {', '.join(detections)}",
                details={"patterns": detections},
                score=0.9,
            )

        return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False, message="No leakage")
