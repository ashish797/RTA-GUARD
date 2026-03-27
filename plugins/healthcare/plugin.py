"""Healthcare PII & HIPAA Protection Plugin"""
import re
from discus.plugins import PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity


class Plugin(PluginBase):
    patterns = {
        "medical_record_number": re.compile(r"MRN[:\s]*(\d{6,10})", re.IGNORECASE),
        "icd10_code": re.compile(r"\b([A-TV-Z]\d{2}\.?\d{0,4})\b"),
        "npi_number": re.compile(r"\bNPI[:\s]*(\d{10})\b", re.IGNORECASE),
        "insurance_id": re.compile(r"\b([A-Z]{3}\d{9})\b"),
        "dea_number": re.compile(r"\b([A-Z]{2}\d{7})\b"),
        "patient_name_context": re.compile(r"\bpatient[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)", re.IGNORECASE),
        "diagnosis_context": re.compile(r"\bdiagnos(?:is|ed)[:\s]+(.{5,50})", re.IGNORECASE),
    }

    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        text = context.input_text if hook == PluginHook.ON_INPUT else context.output_text
        matches = []

        for name, pattern in self.patterns.items():
            found = pattern.findall(text)
            if found:
                matches.append({"type": name, "values": found[:3]})

        if matches:
            return PluginResult(
                plugin_id=self.plugin_id,
                hook=hook,
                violated=True,
                severity=PluginSeverity.KILL,
                message=f"HIPAA violation: detected {len(matches)} PHI pattern(s)",
                details={"matches": matches},
                score=min(1.0, len(matches) * 0.3),
            )

        return PluginResult(
            plugin_id=self.plugin_id,
            hook=hook,
            violated=False,
            message="No PHI detected",
        )
