"""
RTA-GUARD — Custom Rules & Multi-Tenant System

YAML-based rule profiles with inheritance, per-tenant configuration,
per-chain rule engines, and dynamic rule loading.

Usage:
    from discus.rules.profile import GuardProfile, RuleProfileManager

    # Load a profile
    profile = GuardProfile.from_yaml("profiles/strict.yaml")

    # Use with guard
    engine = RuleEngine.from_profile(profile)
    result = engine.check("user input")
"""
import copy
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import yaml

logger = logging.getLogger("discus.rules.profile")


# ═══════════════════════════════════════════════════════════════════
# Rule Configuration Data Classes
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RuleConfig:
    """Configuration for a single rule."""
    enabled: bool = True
    action: str = "kill"  # kill, warn, pass
    threshold: float = 0.5
    categories: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    message: str = ""
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "action": self.action,
            "threshold": self.threshold,
            "categories": self.categories,
            "patterns": self.patterns,
            "message": self.message,
            "custom": self.custom,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleConfig":
        return cls(
            enabled=data.get("enabled", True),
            action=data.get("action", "kill"),
            threshold=data.get("threshold", 0.5),
            categories=data.get("categories", []),
            patterns=data.get("patterns", []),
            message=data.get("message", ""),
            custom=data.get("custom", {}),
        )


@dataclass
class StreamingConfig:
    """Streaming configuration."""
    check_every_n_chars: int = 10
    buffer_size: int = 200
    early_termination: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StreamingConfig":
        return cls(
            check_every_n_chars=data.get("check_every_n_chars", 10),
            buffer_size=data.get("buffer_size", 200),
            early_termination=data.get("early_termination", True),
        )


@dataclass
class MemoryConfig:
    """Conversation memory configuration."""
    enabled: bool = True
    max_messages: int = 50
    expiry_seconds: int = 1800
    profile_threshold: float = 0.5
    contradiction_threshold: int = 3
    drift_threshold: float = 0.4

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryConfig":
        return cls(
            enabled=data.get("enabled", True),
            max_messages=data.get("max_messages", 50),
            expiry_seconds=data.get("expiry_seconds", 1800),
            profile_threshold=data.get("profile_threshold", 0.5),
            contradiction_threshold=data.get("contradiction_threshold", 3),
            drift_threshold=data.get("drift_threshold", 0.4),
        )


@dataclass
class CustomRule:
    """A custom user-defined rule."""
    name: str
    patterns: List[str] = field(default_factory=list)
    detect: List[str] = field(default_factory=list)
    action: str = "warn"
    context: str = "single"  # single or multi_turn
    message: str = ""
    enabled: bool = True

    def __post_init__(self):
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.patterns
        ]

    def matches(self, text: str) -> bool:
        """Check if text matches this custom rule."""
        for pattern in self._compiled_patterns:
            if pattern.search(text):
                return True
        for keyword in self.detect:
            if keyword.lower() in text.lower():
                return True
        return False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomRule":
        return cls(
            name=data["name"],
            patterns=data.get("patterns", []),
            detect=data.get("detect", []),
            action=data.get("action", "warn"),
            context=data.get("context", "single"),
            message=data.get("message", ""),
            enabled=data.get("enabled", True),
        )


# ═══════════════════════════════════════════════════════════════════
# Guard Profile
# ═══════════════════════════════════════════════════════════════════

@dataclass
class GuardProfile:
    """
    A named configuration of guard rules.

    Loaded from YAML, supports inheritance (include),
    and can be composed with tenant-specific overrides.
    """
    name: str
    description: str = ""
    rules: Dict[str, RuleConfig] = field(default_factory=dict)
    custom_rules: List[CustomRule] = field(default_factory=list)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    plugins: List[str] = field(default_factory=list)
    webhooks: List[Dict[str, Any]] = field(default_factory=list)
    includes: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str, search_dirs: Optional[List[str]] = None) -> "GuardProfile":
        """Load a profile from YAML file, resolving includes."""
        file_path = cls._find_file(path, search_dirs)
        with open(file_path) as f:
            data = yaml.safe_load(f)

        # Resolve includes recursively
        data = cls._resolve_includes(data, file_path.parent, search_dirs, set())

        return cls._from_data(data, Path(path).stem)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], name: str = "unnamed") -> "GuardProfile":
        """Create profile from dictionary."""
        return cls._from_data(data, name)

    @classmethod
    def _from_data(cls, data: Dict[str, Any], name: str) -> "GuardProfile":
        """Create profile from resolved data dict."""
        rules = {}
        for rule_name, rule_data in data.get("rules", {}).items():
            if isinstance(rule_data, dict):
                rules[rule_name] = RuleConfig.from_dict(rule_data)

        custom_rules = []
        for cr in data.get("custom_rules", data.get("rules", {}).get("custom", [])):
            if isinstance(cr, dict) and "name" in cr:
                custom_rules.append(CustomRule.from_dict(cr))

        return cls(
            name=data.get("name", name),
            description=data.get("description", ""),
            rules=rules,
            custom_rules=custom_rules,
            streaming=StreamingConfig.from_dict(data.get("streaming", {})),
            memory=MemoryConfig.from_dict(data.get("memory", {})),
            plugins=data.get("plugins", []),
            webhooks=data.get("webhooks", []),
            includes=data.get("_includes_resolved", []),
        )

    @classmethod
    def _resolve_includes(self, data: Dict[str, Any], base_dir: Path,
                          search_dirs: Optional[List[str]], seen: Set[str]) -> Dict[str, Any]:
        """Resolve include directives, merging parent configs."""
        includes = data.pop("include", [])
        if isinstance(includes, str):
            includes = [includes]

        merged: Dict[str, Any] = {}
        for include_path in includes:
            if include_path in seen:
                continue
            seen.add(include_path)

            file_path = self._find_file(include_path, search_dirs, base_dir)
            with open(file_path) as f:
                parent_data = yaml.safe_load(f)

            # Recursively resolve parent includes
            parent_data = self._resolve_includes(parent_data, file_path.parent, search_dirs, seen)

            # Deep merge parent into merged
            merged = self._deep_merge(merged, parent_data)

        # Merge current data on top
        merged = self._deep_merge(merged, data)
        return merged

    @staticmethod
    def _deep_merge(base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries. Override values take precedence."""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = GuardProfile._deep_merge(result[key], value)
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                result[key] = result[key] + value
            else:
                result[key] = copy.deepcopy(value)
        return result

    @staticmethod
    def _find_file(path: str, search_dirs: Optional[List[str]] = None,
                   base_dir: Optional[Path] = None) -> Path:
        """Find a file in search directories."""
        p = Path(path)
        if p.is_absolute() and p.exists():
            return p

        # Try relative to base_dir
        if base_dir:
            candidate = base_dir / path
            if candidate.exists():
                return candidate

        # Try search directories
        if search_dirs:
            for d in search_dirs:
                candidate = Path(d) / path
                if candidate.exists():
                    return candidate

        # Try current directory
        if Path(path).exists():
            return Path(path)

        raise FileNotFoundError(f"Profile not found: {path}")

    def get_rule(self, rule_name: str) -> Optional[RuleConfig]:
        """Get a rule configuration by name."""
        return self.rules.get(rule_name)

    def is_rule_enabled(self, rule_name: str) -> bool:
        """Check if a rule is enabled."""
        rule = self.rules.get(rule_name)
        return rule is not None and rule.enabled

    def get_action(self, rule_name: str) -> str:
        """Get the action for a rule."""
        rule = self.rules.get(rule_name)
        return rule.action if rule else "pass"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "rules": {k: v.to_dict() for k, v in self.rules.items()},
            "custom_rules": [{"name": cr.name, "action": cr.action} for cr in self.custom_rules],
            "streaming": {
                "check_every_n_chars": self.streaming.check_every_n_chars,
                "buffer_size": self.streaming.buffer_size,
                "early_termination": self.streaming.early_termination,
            },
            "memory": {
                "enabled": self.memory.enabled,
                "max_messages": self.memory.max_messages,
                "profile_threshold": self.memory.profile_threshold,
            },
            "plugins": self.plugins,
        }


# ═══════════════════════════════════════════════════════════════════
# Profile-Based Rule Engine
# ═══════════════════════════════════════════════════════════════════

class ProfileRuleEngine:
    """
    Rule engine that uses a GuardProfile for configuration.
    Applies rules based on profile settings.
    """

    def __init__(self, profile: GuardProfile):
        self.profile = profile
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns from profile."""
        for rule_name, rule_config in self.profile.rules.items():
            if rule_config.patterns:
                self._compiled_patterns[rule_name] = [
                    re.compile(p, re.IGNORECASE) for p in rule_config.patterns
                ]

    def check(self, text: str, session_id: str = "default") -> "ProfileCheckResult":
        """Check text against all enabled rules in the profile."""
        violations = []

        # Check built-in rules
        for rule_name, rule_config in self.profile.rules.items():
            if not rule_config.enabled:
                continue

            violated = False
            details = {}

            # Pattern-based rules
            if rule_name in self._compiled_patterns:
                for pattern in self._compiled_patterns[rule_name]:
                    match = pattern.search(text)
                    if match:
                        violated = True
                        details["matched_pattern"] = pattern.pattern
                        details["matched_text"] = match.group()
                        break

            # Category-based rules (PII categories in text)
            if rule_config.categories and not violated:
                text_lower = text.lower()
                for cat in rule_config.categories:
                    if cat in text_lower:
                        violated = True
                        details["detected_category"] = cat
                        break

            if violated:
                violations.append({
                    "rule": rule_name,
                    "action": rule_config.action,
                    "message": rule_config.message or f"Rule {rule_name} violated",
                    "details": details,
                })

        # Check custom rules
        for custom_rule in self.profile.custom_rules:
            if not custom_rule.enabled:
                continue
            if custom_rule.matches(text):
                violations.append({
                    "rule": f"custom:{custom_rule.name}",
                    "action": custom_rule.action,
                    "message": custom_rule.message or f"Custom rule {custom_rule.name} violated",
                    "details": {"patterns": custom_rule.patterns},
                })

        # Determine overall result
        worst_action = "pass"
        for v in violations:
            if v["action"] == "kill":
                worst_action = "kill"
                break
            elif v["action"] == "warn" and worst_action != "kill":
                worst_action = "warn"

        return ProfileCheckResult(
            profile_name=self.profile.name,
            session_id=session_id,
            decision=worst_action,
            violations=violations,
            rules_checked=len([r for r in self.profile.rules.values() if r.enabled]),
            custom_rules_checked=len([r for r in self.profile.custom_rules if r.enabled]),
        )


@dataclass
class ProfileCheckResult:
    """Result of a profile-based rule check."""
    profile_name: str
    session_id: str
    decision: str  # pass, warn, kill
    violations: List[Dict[str, Any]]
    rules_checked: int
    custom_rules_checked: int
    timestamp: float = field(default_factory=time.time)

    @property
    def passed(self) -> bool:
        return self.decision == "pass"

    @property
    def killed(self) -> bool:
        return self.decision == "kill"

    @property
    def warned(self) -> bool:
        return self.decision == "warn"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "session_id": self.session_id,
            "decision": self.decision,
            "violations": self.violations,
            "rules_checked": self.rules_checked,
            "custom_rules_checked": self.custom_rules_checked,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════
# Rule Profile Manager
# ═══════════════════════════════════════════════════════════════════

class RuleProfileManager:
    """
    Manages guard profiles with:
    - Loading from YAML files
    - Caching and hot-reloading
    - Per-tenant profile assignment
    - Dynamic rule updates
    """

    def __init__(self, profiles_dir: Optional[str] = None,
                 tenants_dir: Optional[str] = None):
        self.profiles_dir = Path(profiles_dir) if profiles_dir else None
        self.tenants_dir = Path(tenants_dir) if tenants_dir else None
        self._profiles: Dict[str, GuardProfile] = {}
        self._tenant_profiles: Dict[str, str] = {}  # tenant_id -> profile_name
        self._engines: Dict[str, ProfileRuleEngine] = {}
        self._change_callbacks: List[Callable] = []

    def load(self, name: str) -> GuardProfile:
        """Load a profile by name."""
        if name in self._profiles:
            return self._profiles[name]

        search_dirs = []
        if self.profiles_dir:
            search_dirs.append(str(self.profiles_dir))

        profile = GuardProfile.from_yaml(f"{name}.yaml", search_dirs=search_dirs)
        self._profiles[name] = profile
        self._engines[name] = ProfileRuleEngine(profile)
        return profile

    def get_engine(self, name: str) -> ProfileRuleEngine:
        """Get a rule engine for a profile."""
        if name not in self._engines:
            self.load(name)
        return self._engines[name]

    def get_profile_for_tenant(self, tenant_id: str) -> GuardProfile:
        """Get the profile assigned to a tenant."""
        profile_name = self._tenant_profiles.get(tenant_id, "strict")
        return self.load(profile_name)

    def get_engine_for_tenant(self, tenant_id: str) -> ProfileRuleEngine:
        """Get the rule engine for a tenant."""
        profile = self.get_profile_for_tenant(tenant_id)
        return self.get_engine(profile.name)

    def assign_tenant(self, tenant_id: str, profile_name: str):
        """Assign a profile to a tenant."""
        self._tenant_profiles[tenant_id] = profile_name
        self._notify_change(f"tenant_assigned:{tenant_id}:{profile_name}")

    def create(self, name: str, base: Optional[str] = None,
               overrides: Optional[Dict[str, Any]] = None) -> GuardProfile:
        """Create a new profile, optionally inheriting from a base."""
        if base and base in self._profiles:
            base_data = self._profiles[base].to_dict()
            if overrides:
                base_data = GuardProfile._deep_merge(base_data, overrides)
            profile = GuardProfile.from_dict(base_data, name=name)
        else:
            profile = GuardProfile.from_dict(overrides or {}, name=name)

        self._profiles[name] = profile
        self._engines[name] = ProfileRuleEngine(profile)
        self._notify_change(f"profile_created:{name}")
        return profile

    def update_rule(self, profile_name: str, rule_name: str,
                    updates: Dict[str, Any]) -> bool:
        """Update a specific rule in a profile."""
        if profile_name not in self._profiles:
            return False

        profile = self._profiles[profile_name]
        if rule_name not in profile.rules:
            profile.rules[rule_name] = RuleConfig.from_dict(updates)
        else:
            current = profile.rules[rule_name]
            for key, value in updates.items():
                if hasattr(current, key):
                    setattr(current, key, value)

        # Rebuild engine
        self._engines[profile_name] = ProfileRuleEngine(profile)
        self._notify_change(f"rule_updated:{profile_name}:{rule_name}")
        return True

    def delete(self, name: str) -> bool:
        """Delete a profile."""
        if name in self._profiles:
            del self._profiles[name]
            del self._engines[name]
            self._notify_change(f"profile_deleted:{name}")
            return True
        return False

    def list_profiles(self) -> List[Dict[str, Any]]:
        """List all loaded profiles."""
        return [
            {"name": p.name, "description": p.description,
             "rules_count": len(p.rules), "custom_rules_count": len(p.custom_rules)}
            for p in self._profiles.values()
        ]

    def reload(self, name: str) -> GuardProfile:
        """Reload a profile from disk (hot reload)."""
        if name in self._profiles:
            del self._profiles[name]
            del self._engines[name]
        profile = self.load(name)
        self._notify_change(f"profile_reloaded:{name}")
        return profile

    def on_change(self, callback: Callable):
        """Register a callback for profile changes."""
        self._change_callbacks.append(callback)

    def _notify_change(self, event: str):
        for cb in self._change_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.warning(f"Change callback error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "profiles_loaded": len(self._profiles),
            "tenants_assigned": len(self._tenant_profiles),
            "profile_names": list(self._profiles.keys()),
            "tenant_assignments": dict(self._tenant_profiles),
        }
