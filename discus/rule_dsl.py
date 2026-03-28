"""
RTA-GUARD — Rule DSL (Domain-Specific Language)

A human-readable rule definition language for RTA-GUARD.
Allows non-engineers to define guardrails without Python.

Syntax:
    RULE rule_name:
      IF input MATCHES pattern OR output CONTAINS ["item1", "item2"]
      THEN KILL "reason message"
      PRIORITY CRITICAL
      CATEGORY injection
"""
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("rta_guard.rule_dsl")


# ═══════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RuleCondition:
    """A single condition in a rule."""
    target: str  # "input", "output", "confidence", "session_violations"
    operator: str  # "matches", "contains", "length_gt", "length_lt", "lt", "gt", "eq"
    value: Any
    negated: bool = False

    def __repr__(self):
        neg = "NOT " if self.negated else ""
        return f"{neg}{self.target} {self.operator} {self.value}"


@dataclass
class RuleAction:
    """Action to take when a rule matches."""
    type: str  # "kill", "block", "warn", "throttle"
    reason: str
    delay_ms: int = 0


@dataclass
class RuleDefinition:
    """Complete rule definition parsed from DSL."""
    name: str
    conditions: List[RuleCondition]
    action: RuleAction
    priority: int
    category: str
    enabled: bool = True
    description: str = ""
    logical_op: str = "AND"  # "AND" or "OR" for combining conditions


@dataclass
class RuleResult:
    """Result of evaluating a rule."""
    rule_name: str
    matched: bool
    action: RuleAction
    matched_conditions: List[str]
    timestamp: float


@dataclass
class ValidationError:
    """A validation error found in rules."""
    rule_name: str
    message: str
    severity: str  # "error", "warning"


# ═══════════════════════════════════════════════════════════════════
# Priority Mapping
# ═══════════════════════════════════════════════════════════════════

PRIORITY_MAP = {
    "CRITICAL": 100,
    "HIGH": 75,
    "MEDIUM": 50,
    "LOW": 25,
}

PRIORITY_REVERSE = {v: k for k, v in PRIORITY_MAP.items()}


# ═══════════════════════════════════════════════════════════════════
# Built-in Patterns
# ═══════════════════════════════════════════════════════════════════

BUILTIN_PATTERNS = {
    "ssn_pattern": r"\b\d{3}-\d{2}-\d{4}\b",
    "email_pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "credit_card_pattern": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "phone_pattern": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ip_pattern": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "injection_pattern": r"(?i)(ignore\s+(all\s+)?previous|disregard\s+(the\s+)?(system|prior)|override\s+(safety|instructions)|new\s+instructions|forget\s+your\s+rules|bypass\s+(content\s+)?filter)",
    "jailbreak_pattern": r"(?i)(DAN\s+mode|do\s+anything\s+now|developer\s+mode|act\s+as\s+if\s+you\s+have\s+no|you\s+are\s+not\s+bound\s+by|ignore\s+ethical\s+guidelines|roleplay\s+as|pretend\s+to\s+be\s+an?\s+unrestricted)",
    "medical_record_pattern": r"\b(?:MRN|Medical Record|Patient ID)[:\s]*\d{6,10}\b",
}


# ═══════════════════════════════════════════════════════════════════
# Parser
# ═══════════════════════════════════════════════════════════════════

class RuleDSLParser:
    """Parses DSL text into RuleDefinition objects.

    Usage:
        parser = RuleDSLParser()
        rules = parser.parse('''
            RULE block_ssn:
              IF output MATCHES ssn_pattern
              THEN KILL "SSN detected"
              PRIORITY CRITICAL
              CATEGORY pii
        ''')
    """

    def __init__(self):
        self.patterns = dict(BUILTIN_PATTERNS)
        self._compiled_patterns: Dict[str, re.Pattern] = {}
        for name, pat in self.patterns.items():
            self._compiled_patterns[name] = re.compile(pat)

    def register_pattern(self, name: str, pattern: str):
        """Add a custom named pattern.

        Args:
            name: Pattern name (used in MATCHES clauses)
            pattern: Regex pattern string
        """
        self.patterns[name] = pattern
        self._compiled_patterns[name] = re.compile(pattern)

    def parse(self, dsl_text: str) -> List[RuleDefinition]:
        """Parse DSL text into rule definitions.

        Args:
            dsl_text: The DSL text to parse
        Returns:
            List of RuleDefinition objects
        """
        rules = []
        lines = dsl_text.strip().split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.upper().startswith("RULE "):
                rule, consumed = self._parse_rule(lines, i)
                if rule:
                    rules.append(rule)
                i += consumed
            else:
                i += 1
        return rules

    def _parse_rule(self, lines: List[str], start: int) -> Tuple[Optional[RuleDefinition], int]:
        """Parse a single rule starting at line `start`."""
        header = lines[start].strip()
        # RULE name:
        match = re.match(r"RULE\s+([a-zA-Z_][a-zA-Z0-9_]*):?\s*(.*)", header)
        if not match:
            return None, 1
        name = match.group(1)
        rest_of_header = match.group(2).strip()

        conditions: List[RuleCondition] = []
        action: Optional[RuleAction] = None
        priority = 50
        category = "general"
        description = ""
        logical_op = "AND"
        i = start + 1
        indent_level = None

        # Build all lines to parse (header rest + subsequent lines)
        all_lines_to_parse = []
        if rest_of_header:
            all_lines_to_parse.append(rest_of_header)

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith("#"):
                i += 1
                continue

            # Determine indent level from first indented line
            if indent_level is None and line and line[0] == " ":
                indent_level = len(line) - len(line.lstrip())

            # If we hit a new RULE line at the same or lower indent level, stop
            if stripped.upper().startswith("RULE "):
                if indent_level is not None:
                    break
                # For inline rules (indent_level=None), check if this is a new rule
                # by seeing if it comes after we've already started processing
                if i > start + 1 or (i == start + 1 and not rest_of_header):
                    break

            all_lines_to_parse.append(stripped)
            i += 1

        # Process all lines (header rest + body) for IF/THEN/PRIORITY/CATEGORY
        for stripped in all_lines_to_parse:
            upper = stripped.upper()
            if upper.startswith("IF "):
                # Parse conditions — but also check for inline THEN/PRIORITY/CATEGORY
                cond_text = stripped[3:].strip()
                then_match = re.search(r"\bTHEN\b", cond_text, re.IGNORECASE)
                if then_match:
                    conditions, logical_op = self._parse_conditions(cond_text[:then_match.start()].strip())
                else:
                    conditions, logical_op = self._parse_conditions(cond_text)
            if (upper.startswith("THEN ") or " THEN " in upper) and not action:
                # Parse action
                if upper.startswith("THEN "):
                    action_text = stripped[5:].strip()
                else:
                    then_pos = upper.find(" THEN ")
                    action_text = stripped[then_pos + 6:].strip()
                # Strip PRIORITY/CATEGORY
                for kw in (" PRIORITY ", " CATEGORY "):
                    kw_pos = action_text.upper().find(kw)
                    if kw_pos > 0:
                        action_text = action_text[:kw_pos].strip()
                action = self._parse_action(action_text)
            if "PRIORITY " in upper and priority == 50:
                m = re.search(r"PRIORITY\s+(CRITICAL|HIGH|MEDIUM|LOW)", upper)
                if m:
                    priority = PRIORITY_MAP.get(m.group(1), 50)
            if "CATEGORY " in upper and category == "general":
                m = re.search(r"CATEGORY\s+(\w+)", upper)
                if m:
                    category = m.group(1).lower()
            if upper.startswith("DESCRIPTION "):
                description = stripped.split(None, 1)[1].strip().strip('"') if len(stripped.split(None, 1)) > 1 else ""

        if not action:
            action = RuleAction(type="warn", reason=f"Rule {name} triggered")

        rule = RuleDefinition(
            name=name,
            conditions=conditions,
            action=action,
            priority=priority,
            category=category,
            description=description,
            logical_op=logical_op,
        )
        return rule, i - start

    def _parse_conditions(self, cond_text: str) -> Tuple[List[RuleCondition], str]:
        """Parse IF conditions, supporting AND/OR."""
        conditions = []
        logical_op = "AND"

        # Split by OR first
        if " OR " in cond_text.upper():
            parts = re.split(r"\s+OR\s+", cond_text, flags=re.IGNORECASE)
            logical_op = "OR"
        else:
            parts = re.split(r"\s+AND\s+", cond_text, flags=re.IGNORECASE)
            logical_op = "AND"

        for part in parts:
            cond = self._parse_single_condition(part.strip())
            if cond:
                conditions.append(cond)

        return conditions, logical_op

    def _parse_single_condition(self, text: str) -> Optional[RuleCondition]:
        """Parse a single condition like 'input MATCHES ssn_pattern'."""
        negated = False
        if text.upper().startswith("NOT "):
            negated = True
            text = text[4:].strip()

        # MATCHES: target MATCHES pattern_name
        m = re.match(r"(input|output)\s+MATCHES\s+(\w+)", text, re.IGNORECASE)
        if m:
            return RuleCondition(
                target=m.group(1).lower(),
                operator="matches",
                value=m.group(2),
                negated=negated,
            )

        # CONTAINS: target CONTAINS ["str1", "str2"]
        m = re.match(r"(input|output)\s+CONTAINS\s+\[([^\]]+)\]", text, re.IGNORECASE)
        if m:
            items_str = m.group(2)
            items = [s.strip().strip('"').strip("'") for s in items_str.split(",")]
            return RuleCondition(
                target=m.group(1).lower(),
                operator="contains",
                value=items,
                negated=negated,
            )

        # LENGTH: target LENGTH > N
        m = re.match(r"(input|output)\s+LENGTH\s*([><=]+)\s*(\d+)", text, re.IGNORECASE)
        if m:
            op = m.group(2)
            val = int(m.group(3))
            if op == ">":
                operator = "length_gt"
            elif op == "<":
                operator = "length_lt"
            else:
                operator = "length_eq"
            return RuleCondition(
                target=m.group(1).lower(),
                operator=operator,
                value=val,
                negated=negated,
            )

        # confidence/session_violations: target op N
        m = re.match(r"(confidence|session_violations)\s*([><=]+)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            target = m.group(1).lower()
            op = m.group(2)
            val = float(m.group(3)) if "." in m.group(3) else int(m.group(3))
            if op == "<":
                operator = "lt"
            elif op == ">":
                operator = "gt"
            else:
                operator = "eq"
            return RuleCondition(
                target=target,
                operator=operator,
                value=val,
                negated=negated,
            )

        return None

    def _parse_action(self, action_text: str) -> RuleAction:
        """Parse THEN action."""
        # KILL "reason"
        m = re.match(r'(KILL|BLOCK|WARN)\s+"([^"]*)"', action_text, re.IGNORECASE)
        if m:
            return RuleAction(type=m.group(1).lower(), reason=m.group(2))

        # THROTTLE "reason" delay_ms
        m = re.match(r'(THROTTLE)\s+"([^"]*)"\s+(\d+)', action_text, re.IGNORECASE)
        if m:
            return RuleAction(type="throttle", reason=m.group(2), delay_ms=int(m.group(3)))

        # Fallback
        parts = action_text.split(None, 1)
        action_type = parts[0].lower() if parts else "warn"
        reason = parts[1].strip().strip('"') if len(parts) > 1 else "Rule triggered"
        return RuleAction(type=action_type, reason=reason)

    def parse_file(self, filepath: str) -> List[RuleDefinition]:
        """Parse a DSL file.

        Args:
            filepath: Path to .rta rules file
        Returns:
            List of RuleDefinition objects
        """
        with open(filepath, "r") as f:
            return self.parse(f.read())

    def validate(self, rules: List[RuleDefinition]) -> List[ValidationError]:
        """Validate parsed rules.

        Args:
            rules: List of rules to validate
        Returns:
            List of validation errors
        """
        errors = []
        seen_names = set()

        for rule in rules:
            # Check duplicate names
            if rule.name in seen_names:
                errors.append(ValidationError(
                    rule_name=rule.name,
                    message=f"Duplicate rule name: {rule.name}",
                    severity="error",
                ))
            seen_names.add(rule.name)

            # Check conditions reference valid patterns
            for cond in rule.conditions:
                if cond.operator == "matches" and cond.value not in self.patterns:
                    errors.append(ValidationError(
                        rule_name=rule.name,
                        message=f"Unknown pattern: {cond.value}",
                        severity="error",
                    ))

            # Check valid action type
            if rule.action.type not in ("kill", "block", "warn", "throttle"):
                errors.append(ValidationError(
                    rule_name=rule.name,
                    message=f"Invalid action type: {rule.action.type}",
                    severity="error",
                ))

            # Check valid target
            for cond in rule.conditions:
                if cond.target not in ("input", "output", "confidence", "session_violations"):
                    errors.append(ValidationError(
                        rule_name=rule.name,
                        message=f"Invalid condition target: {cond.target}",
                        severity="error",
                    ))

        return errors


# ═══════════════════════════════════════════════════════════════════
# Compiled Rule
# ═══════════════════════════════════════════════════════════════════

class CompiledRule:
    """A rule compiled for efficient evaluation.

    Usage:
        compiler = RuleCompiler()
        compiled = compiler.compile(rule_definition)
        result = compiled.evaluate("user input", "llm output", {"confidence": 0.9})
    """

    def __init__(self, definition: RuleDefinition, patterns: Dict[str, re.Pattern]):
        self.definition = definition
        self.name = definition.name
        self.priority = definition.priority
        self.category = definition.category
        self.action = definition.action
        self.enabled = definition.enabled
        self._patterns = patterns
        self._condition_fns = self._compile_conditions(definition.conditions)

    def _compile_conditions(self, conditions: List[RuleCondition]) -> List[Callable]:
        """Compile conditions into callable functions."""
        fns = []
        for cond in conditions:
            fns.append(self._make_condition_fn(cond))
        return fns

    def _make_condition_fn(self, cond: RuleCondition) -> Callable:
        """Create a function that evaluates a single condition."""
        def check(input_text: str, output_text: str, context: Dict) -> Tuple[bool, str]:
            # Get the text to check
            if cond.target == "input":
                text = input_text
            elif cond.target == "output":
                text = output_text
            elif cond.target == "confidence":
                val = context.get("confidence", 1.0)
                result = self._compare_op(val, cond.operator, cond.value)
                return (not result if cond.negated else result, f"confidence {cond.operator} {cond.value}")
            elif cond.target == "session_violations":
                val = context.get("session_violations", 0)
                result = self._compare_op(val, cond.operator, cond.value)
                return (not result if cond.negated else result, f"session_violations {cond.operator} {cond.value}")
            else:
                return (False, "unknown target")

            result = self._check_text(text, cond)
            return (not result if cond.negated else result, f"{cond.target} {cond.operator} {cond.value}")

        return check

    def _check_text(self, text: str, cond: RuleCondition) -> bool:
        """Check text against a condition."""
        if not text:
            return False

        if cond.operator == "matches":
            pattern = self._patterns.get(cond.value)
            if pattern:
                return bool(pattern.search(text))
            return False

        elif cond.operator == "contains":
            text_lower = text.lower()
            for item in cond.value:
                if item.lower() in text_lower:
                    return True
            return False

        elif cond.operator == "length_gt":
            return len(text) > cond.value

        elif cond.operator == "length_lt":
            return len(text) < cond.value

        elif cond.operator == "length_eq":
            return len(text) == cond.value

        return False

    def _compare_op(self, val: Any, operator: str, target: Any) -> bool:
        """Compare values with operator."""
        if operator == "lt":
            return val < target
        elif operator == "gt":
            return val > target
        elif operator == "eq":
            return val == target
        elif operator == "gte":
            return val >= target
        elif operator == "lte":
            return val <= target
        return False

    def evaluate(self, input_text: str, output_text: str,
                 context: Optional[Dict] = None) -> Optional[RuleResult]:
        """Evaluate the rule against input/output.

        Args:
            input_text: User input
            output_text: LLM output
            context: Additional context (confidence, session_violations, etc.)
        Returns:
            RuleResult if matched, None if not
        """
        if not self.enabled:
            return None

        ctx = context or {}
        matched_conditions = []
        results = []

        for fn in self._condition_fns:
            matched, desc = fn(input_text, output_text, ctx)
            results.append(matched)
            if matched:
                matched_conditions.append(desc)

        # Apply logical operator
        if self.definition.logical_op == "AND":
            any_matched = all(results) if results else False
        else:  # OR
            any_matched = any(results) if results else False

        if any_matched:
            return RuleResult(
                rule_name=self.name,
                matched=True,
                action=self.action,
                matched_conditions=matched_conditions,
                timestamp=time.time(),
            )
        return None


# ═══════════════════════════════════════════════════════════════════
# Compiler
# ═══════════════════════════════════════════════════════════════════

class RuleCompiler:
    """Compiles RuleDefinitions into CompiledRules.

    Usage:
        compiler = RuleCompiler()
        compiled_rules = compiler.compile_all(definitions)
    """

    def __init__(self, patterns: Optional[Dict[str, str]] = None):
        self.patterns = patterns or dict(BUILTIN_PATTERNS)
        self._compiled = {}
        for name, pat in self.patterns.items():
            self._compiled[name] = re.compile(pat)

    def compile(self, definition: RuleDefinition) -> CompiledRule:
        """Compile a single rule definition.

        Args:
            definition: The rule to compile
        Returns:
            CompiledRule ready for evaluation
        """
        return CompiledRule(definition, self._compiled)

    def compile_all(self, definitions: List[RuleDefinition]) -> List[CompiledRule]:
        """Compile all rules, sorted by priority descending.

        Args:
            definitions: List of rule definitions
        Returns:
            List of compiled rules, highest priority first
        """
        compiled = [self.compile(d) for d in definitions if d.enabled]
        compiled.sort(key=lambda r: r.priority, reverse=True)
        return compiled


# ═══════════════════════════════════════════════════════════════════
# Validator
# ═══════════════════════════════════════════════════════════════════

class RuleValidator:
    """Validates rule definitions for correctness.

    Usage:
        validator = RuleValidator()
        errors = validator.validate(rules)
    """

    def validate(self, definitions: List[RuleDefinition]) -> List[ValidationError]:
        """Validate a list of rule definitions.

        Args:
            definitions: Rules to validate
        Returns:
            List of validation errors
        """
        errors = []
        seen_names = set()

        for defn in definitions:
            # Duplicate names
            if defn.name in seen_names:
                errors.append(ValidationError(
                    rule_name=defn.name,
                    message=f"Duplicate rule name: {defn.name}",
                    severity="error",
                ))
            seen_names.add(defn.name)

            # No conditions
            if not defn.conditions:
                errors.append(ValidationError(
                    rule_name=defn.name,
                    message="Rule has no conditions",
                    severity="warning",
                ))

            # Invalid action
            if defn.action.type not in ("kill", "block", "warn", "throttle"):
                errors.append(ValidationError(
                    rule_name=defn.name,
                    message=f"Invalid action: {defn.action.type}",
                    severity="error",
                ))

        # Check for conflicts
        conflicts = self.check_conflicts(definitions)
        for r1, r2 in conflicts:
            errors.append(ValidationError(
                rule_name=f"{r1} vs {r2}",
                message=f"Conflicting rules: {r1} and {r2}",
                severity="warning",
            ))

        return errors

    def check_conflicts(self, rules: List[RuleDefinition]) -> List[Tuple[str, str]]:
        """Find rules with same conditions but different actions.

        Args:
            rules: Rules to check
        Returns:
            List of (rule_name_1, rule_name_2) tuples for conflicting pairs
        """
        conflicts = []
        for i, r1 in enumerate(rules):
            for r2 in rules[i + 1:]:
                if self._same_conditions(r1, r2) and r1.action.type != r2.action.type:
                    conflicts.append((r1.name, r2.name))
        return conflicts

    def _same_conditions(self, r1: RuleDefinition, r2: RuleDefinition) -> bool:
        """Check if two rules have the same conditions."""
        if len(r1.conditions) != len(r2.conditions):
            return False
        for c1, c2 in zip(r1.conditions, r2.conditions):
            if (c1.target != c2.target or c1.operator != c2.operator or
                    c1.value != c2.value or c1.negated != c2.negated):
                return False
        return True


# ═══════════════════════════════════════════════════════════════════
# Hot Reload Manager
# ═══════════════════════════════════════════════════════════════════

class HotReloadRuleManager:
    """Manages rules with hot-reload from a file.

    Usage:
        manager = HotReloadRuleManager("/path/to/rules.rta", compiler, validator)
        rules = manager.load()
        # Later...
        if manager.reload_if_changed():
            rules = manager.get_active_rules()
    """

    def __init__(self, filepath: str, compiler: RuleCompiler,
                 validator: Optional[RuleValidator] = None):
        self.filepath = filepath
        self.compiler = compiler
        self.validator = validator or RuleValidator()
        self._active_rules: List[CompiledRule] = []
        self._last_mtime: float = 0
        self._last_load_time: float = 0

    def load(self) -> List[CompiledRule]:
        """Load rules from file.

        Returns:
            List of compiled rules
        """
        if not os.path.exists(self.filepath):
            logger.warning(f"Rules file not found: {self.filepath}")
            return []

        parser = RuleDSLParser()
        definitions = parser.parse_file(self.filepath)

        # Validate
        errors = self.validator.validate(definitions)
        for err in errors:
            if err.severity == "error":
                logger.error(f"Rule validation error: {err.rule_name}: {err.message}")
            else:
                logger.warning(f"Rule validation warning: {err.rule_name}: {err.message}")

        self._active_rules = self.compiler.compile_all(definitions)
        self._last_mtime = os.path.getmtime(self.filepath)
        self._last_load_time = time.time()

        logger.info(f"Loaded {len(self._active_rules)} rules from {self.filepath}")
        return self._active_rules

    def reload_if_changed(self) -> bool:
        """Check if file changed and reload if so.

        Returns:
            True if reloaded, False if no change
        """
        if not os.path.exists(self.filepath):
            return False

        current_mtime = os.path.getmtime(self.filepath)
        if current_mtime > self._last_mtime:
            logger.info(f"Rules file changed, reloading: {self.filepath}")
            self.load()
            return True
        return False

    def get_active_rules(self) -> List[CompiledRule]:
        """Get the currently active compiled rules.

        Returns:
            List of compiled rules
        """
        return self._active_rules
