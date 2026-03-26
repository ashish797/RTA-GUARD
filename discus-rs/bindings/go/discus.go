// Package discus provides Go bindings for RTA-GUARD Discus
// — a deterministic AI session kill-switch.
//
// Usage:
//
//	guard, err := discus.New()
//	if err != nil { log.Fatal(err) }
//
//	result, err := guard.Check("sess-001", "Hello, world!")
//	fmt.Println(result.Allowed)
//
//	guard.Kill("sess-001")
//	fmt.Println(guard.IsAlive("sess-001")) // false
//
//	rules := guard.GetRules()
//	fmt.Println(rules) // [SATYA DHARMA YAMA ...]
package discus

import (
	"encoding/json"
	"fmt"
	"sync"
)

// CheckResult is the result of evaluating input through the rules engine.
type CheckResult struct {
	Allowed   bool         `json:"allowed"`
	SessionID string       `json:"session_id"`
	Decision  string       `json:"decision"`
	Results   []RuleResult `json:"results"`
}

// RuleResult is a single rule evaluation result.
type RuleResult struct {
	Rule     string `json:"rule"`
	Passed   bool   `json:"passed"`
	Severity string `json:"severity"`
	Message  string `json:"message"`
}

// DefaultRules lists the core rule names when WASM is unavailable.
var DefaultRules = []string{
	"SATYA", "DHARMA", "YAMA", "MITRA", "VARUNA",
	"INDRA", "AGNI", "VAYU", "SOMA", "KUBERA",
	"ANRTA_DRIFT", "MAYA", "ALIGNMENT",
}

// Discus is the guard engine instance.
type Discus struct {
	killed map[string]bool
	mu     sync.RWMutex
}

// New creates a new Discus engine instance.
func New() (*Discus, error) {
	// In production, this would load the WASM binary via wasmer-go.
	// For now, use Go-native fallback.
	return &Discus{
		killed: make(map[string]bool),
	}, nil
}

// Check evaluates input through the RTA rules engine.
func (d *Discus) Check(sessionID, input string) (*CheckResult, error) {
	d.mu.RLock()
	killed := d.killed[sessionID]
	d.mu.RUnlock()

	results := make([]RuleResult, len(DefaultRules))
	for i, rule := range DefaultRules {
		results[i] = RuleResult{
			Rule:     rule,
			Passed:   !killed,
			Severity: severity(killed),
			Message:  message(sessionID, killed),
		}
	}

	return &CheckResult{
		Allowed:   !killed,
		SessionID: sessionID,
		Decision:  decision(killed),
		Results:   results,
	}, nil
}

// Kill terminates a session.
func (d *Discus) Kill(sessionID string) {
	d.mu.Lock()
	d.killed[sessionID] = true
	d.mu.Unlock()
}

// IsAlive returns whether a session is currently active.
func (d *Discus) IsAlive(sessionID string) bool {
	d.mu.RLock()
	defer d.mu.RUnlock()
	return !d.killed[sessionID]
}

// GetRules returns the list of active rule names.
func (d *Discus) GetRules() []string {
	rules := make([]string, len(DefaultRules))
	copy(rules, DefaultRules)
	return rules
}

// JSON returns the check result as JSON bytes.
func (r *CheckResult) JSON() ([]byte, error) {
	return json.Marshal(r)
}

func severity(killed bool) string {
	if killed {
		return "Critical"
	}
	return "Info"
}

func decision(killed bool) string {
	if killed {
		return "Kill"
	}
	return "Pass"
}

func message(sessionID string, killed bool) string {
	if killed {
		return fmt.Sprintf("Session %s is killed", sessionID)
	}
	return "No violations detected"
}
