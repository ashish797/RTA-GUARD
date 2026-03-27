"""Academic Integrity Guard Plugin"""
import re
from discus.plugins import PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity


class Plugin(PluginBase):
    assignment_triggers = [
        re.compile(r"\b(?:write|compose|draft)\s+(?:an?\s+)?(?:essay|paper|report|thesis|dissertation)\b", re.IGNORECASE),
        re.compile(r"\b(?:solve|answer|complete)\s+(?:my\s+)?(?:homework|assignment|quiz|exam|test)\b", re.IGNORECASE),
        re.compile(r"\b(?:do|finish)\s+(?:my\s+)?(?:homework|assignment)\s+(?:for\s+me)?\b", re.IGNORECASE),
        re.compile(r"\bwrite\s+(?:a\s+)?(?:code|program|function)\s+(?:for\s+)?(?:my\s+)?(?:class|course|assignment)\b", re.IGNORECASE),
        re.compile(r"\b(?:help\s+me\s+)?(?:cheat|plagiarize|copy)\b", re.IGNORECASE),
        re.compile(r"\bgenerate\s+(?:a\s+)?(?:bibliography|references|citations)\s+(?:for\s+me)?\b", re.IGNORECASE),
    ]

    educational_context = [
        re.compile(r"\b(?:professor|teacher|instructor|class|course|semester|grade)\b", re.IGNORECASE),
        re.compile(r"\b(?:due\s+date|deadline|rubric|syllabus)\b", re.IGNORECASE),
        re.compile(r"\b(?:GPA|credit\s+hours|enrolled)\b", re.IGNORECASE),
    ]

    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        if hook == PluginHook.ON_INPUT:
            text = context.input_text
        else:
            return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False)

        triggered = any(p.search(text) for p in self.assignment_triggers)
        has_context = any(p.search(text) for p in self.educational_context)

        if triggered:
            confidence = 0.7 if has_context else 0.4
            return PluginResult(
                plugin_id=self.plugin_id,
                hook=hook,
                violated=True,
                severity=PluginSeverity.WARN,
                message="Academic integrity concern: possible assignment completion request",
                details={"has_educational_context": has_context},
                score=confidence,
            )

        return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False, message="Clean")
