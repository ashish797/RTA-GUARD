"""
RTA-GUARD — Jailbreak Detection Heuristics

Adopted from NeMo Guardrails jailbreak_detection/heuristics.

Detects jailbreak attempts using:
1. Length-per-perplexity ratio
2. Prefix-suffix perplexity anomaly

These catch obfuscated jailbreaks that regex patterns miss.
"""
import math
import re
from typing import Optional


class JailbreakHeuristics:
    """
    Heuristic-based jailbreak detection.
    
    Based on NeMo Guardrails' approach:
    - Long prompts with unusual structure → likely jailbreak
    - Prefix-suffix mismatch → likely obfuscation
    """

    # Thresholds (from NeMo defaults)
    LENGTH_PER_PERPLEXITY_THRESHOLD = 8.0
    PREFIX_SUFFIX_PERPLEXITY_THRESHOLD = 1800.0

    def check_length_per_perplexity(self, text: str) -> dict:
        """
        Check if text has unusual length-per-perplexity ratio.
        
        Jailbreaks tend to be long with low perplexity (repetitive).
        """
        if len(text) < 10:
            return {"jailbreak": False, "ratio": 0.0}

        # Simple perplexity approximation using word repetition
        words = text.lower().split()
        if len(words) < 5:
            return {"jailbreak": False, "ratio": 0.0}

        # Count unique words
        unique_words = set(words)
        repetition_ratio = len(words) / len(unique_words) if unique_words else 1.0

        # Length-per-perplexity ratio
        # High ratio = long text with low diversity = suspicious
        ratio = len(text) / repetition_ratio

        is_jailbreak = ratio > self.LENGTH_PER_PERPLEXITY_THRESHOLD * 100

        return {
            "jailbreak": is_jailbreak,
            "ratio": ratio,
            "length": len(text),
            "unique_words": len(unique_words),
            "repetition_ratio": repetition_ratio,
        }

    def check_prefix_suffix_perplexity(self, text: str) -> dict:
        """
        Check if prefix and suffix have different perplexity.
        
        Jailbreaks often have a benign prefix with malicious suffix.
        """
        if len(text) < 20:
            return {"jailbreak": False, "diff": 0.0}

        # Split into prefix and suffix
        mid = len(text) // 2
        prefix = text[:mid]
        suffix = text[mid:]

        # Calculate perplexity approximation for each
        def perplexity_approx(t: str) -> float:
            words = t.lower().split()
            if len(words) < 3:
                return 0.0
            unique = set(words)
            return len(words) / len(unique) if unique else 1.0

        prefix_ppl = perplexity_approx(prefix)
        suffix_ppl = perplexity_approx(suffix)

        # Difference in perplexity
        diff = abs(prefix_ppl - suffix_ppl)

        is_jailbreak = diff > self.PREFIX_SUFFIX_PERPLEXITY_THRESHOLD / 100

        return {
            "jailbreak": is_jailbreak,
            "diff": diff,
            "prefix_ppl": prefix_ppl,
            "suffix_ppl": suffix_ppl,
        }

    def check_structural_anomaly(self, text: str) -> dict:
        """
        Check for structural anomalies common in jailbreaks.
        
        Jailbreaks often have:
        - Excessive newlines
        - Mixed languages/scripts
        - Unusual character patterns
        """
        anomalies = []

        # Excessive newlines
        newline_count = text.count('\n')
        if newline_count > len(text) / 20:  # More than 5% newlines
            anomalies.append(f"excessive_newlines ({newline_count})")

        # Mixed scripts (Latin + Cyrillic + CJK + etc.)
        latin = len(re.findall(r'[a-zA-Z]', text))
        cyrillic = len(re.findall(r'[\u0400-\u04FF]', text))
        cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
        total = latin + cyrillic + cjk
        if total > 0:
            script_ratio = max(cyrillic, cjk) / total
            if script_ratio > 0.3:  # More than 30% non-Latin
                anomalies.append(f"mixed_scripts (ratio: {script_ratio:.2f})")

        # Special character density
        special = len(re.findall(r'[^a-zA-Z0-9\s]', text))
        if special > len(text) * 0.3:  # More than 30% special chars
            anomalies.append(f"high_special_chars ({special}/{len(text)})")

        return {
            "jailbreak": len(anomalies) >= 2,
            "anomalies": anomalies,
        }

    def check(self, text: str) -> dict:
        """
        Full heuristic check.
        
        Returns dict with:
        - jailbreak: bool
        - checks: dict of individual check results
        """
        lp_check = self.check_length_per_perplexity(text)
        ps_check = self.check_prefix_suffix_perplexity(text)
        struct_check = self.check_structural_anomaly(text)

        is_jailbreak = (
            lp_check["jailbreak"] or
            ps_check["jailbreak"] or
            struct_check["jailbreak"]
        )

        return {
            "jailbreak": is_jailbreak,
            "checks": {
                "length_per_perplexity": lp_check,
                "prefix_suffix_perplexity": ps_check,
                "structural_anomaly": struct_check,
            }
        }


# Global instance
_heuristics = None


def check_jailbreak_heuristics(text: str) -> Optional[tuple]:
    """
    Check for jailbreak using heuristics.
    
    Returns (severity, details) or None.
    """
    global _heuristics
    if _heuristics is None:
        _heuristics = JailbreakHeuristics()

    result = _heuristics.check(text)
    if result["jailbreak"]:
        details = []
        for check_name, check_result in result["checks"].items():
            if check_result.get("jailbreak"):
                details.append(check_name)

        return ("HIGH", f"Jailbreak heuristics: {', '.join(details)}")

    return None
