"""XSS Detection Plugin"""
import re
from discus.plugins import PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity


class Plugin(PluginBase):
    xss_patterns = [
        (re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL), "script_tag"),
        (re.compile(r"javascript\s*:", re.IGNORECASE), "javascript_uri"),
        (re.compile(r"on(?:click|load|error|mouseover|focus|blur|submit)\s*=", re.IGNORECASE), "event_handler"),
        (re.compile(r"<(?:iframe|object|embed|applet|form)\b", re.IGNORECASE), "dangerous_tag"),
        (re.compile(r"expression\s*\(", re.IGNORECASE), "css_expression"),
        (re.compile(r"url\s*\(\s*[\"']?\s*javascript:", re.IGNORECASE), "css_url_js"),
        (re.compile(r"data:[^,]*;base64", re.IGNORECASE), "data_uri"),
        (re.compile(r"document\.(?:cookie|location|write|domain)", re.IGNORECASE), "dom_access"),
        (re.compile(r"(?:alert|prompt|confirm)\s*\(", re.IGNORECASE), "dialog_function"),
        (re.compile(r"<(?:img|svg|video)\b[^>]+\bonerror\b", re.IGNORECASE), "media_onerror"),
    ]

    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        text = context.input_text if hook == PluginHook.ON_INPUT else context.output_text
        findings = []

        for pattern, name in self.xss_patterns:
            if pattern.search(text):
                findings.append(name)

        if findings:
            return PluginResult(
                plugin_id=self.plugin_id,
                hook=hook,
                violated=True,
                severity=PluginSeverity.KILL,
                message=f"XSS detected: {', '.join(findings)}",
                details={"patterns": findings},
                score=min(1.0, len(findings) * 0.3),
            )

        return PluginResult(plugin_id=self.plugin_id, hook=hook, violated=False, message="No XSS detected")
