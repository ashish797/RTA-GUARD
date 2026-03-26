package discus

import (
	"fmt"
	"testing"
)

func TestNew(t *testing.T) {
	guard, err := New()
	if err != nil {
		t.Fatalf("New() failed: %v", err)
	}
	if guard == nil {
		t.Fatal("New() returned nil")
	}
}

func TestCheck(t *testing.T) {
	guard, _ := New()
	result, err := guard.Check("test-session", "Hello, world!")
	if err != nil {
		t.Fatalf("Check() failed: %v", err)
	}
	if result.SessionID != "test-session" {
		t.Errorf("session_id = %q, want %q", result.SessionID, "test-session")
	}
	if !result.Allowed {
		t.Error("fresh session should be allowed")
	}
	if result.Decision != "Pass" {
		t.Errorf("decision = %q, want %q", result.Decision, "Pass")
	}
	if len(result.Results) == 0 {
		t.Error("results should not be empty")
	}
}

func TestKillAndIsAlive(t *testing.T) {
	guard, _ := New()
	sessionID := "kill-test"

	if !guard.IsAlive(sessionID) {
		t.Error("session should be alive before kill")
	}

	guard.Kill(sessionID)

	if guard.IsAlive(sessionID) {
		t.Error("session should not be alive after kill")
	}
}

func TestCheckAfterKill(t *testing.T) {
	guard, _ := New()
	sessionID := "check-kill-test"

	result1, _ := guard.Check(sessionID, "test")
	if !result1.Allowed {
		t.Error("session should be allowed before kill")
	}

	guard.Kill(sessionID)

	result2, _ := guard.Check(sessionID, "test")
	if result2.Allowed {
		t.Error("session should not be allowed after kill")
	}
	if result2.Decision != "Kill" {
		t.Errorf("decision = %q, want %q", result2.Decision, "Kill")
	}
}

func TestGetRules(t *testing.T) {
	guard, _ := New()
	rules := guard.GetRules()

	if len(rules) == 0 {
		t.Fatal("rules should not be empty")
	}

	coreRules := map[string]bool{"SATYA": true, "DHARMA": true, "YAMA": true}
	for _, rule := range rules {
		delete(coreRules, rule)
	}
	if len(coreRules) > 0 {
		t.Errorf("missing core rules: %v", coreRules)
	}
}

func TestConcurrentKill(t *testing.T) {
	guard, _ := New()
	done := make(chan bool, 10)

	for i := 0; i < 10; i++ {
		go func(id int) {
			sessionID := fmt.Sprintf("concurrent-%d", id)
			guard.Check(sessionID, "test")
			guard.Kill(sessionID)
			guard.IsAlive(sessionID)
			done <- true
		}(i)
	}

	for i := 0; i < 10; i++ {
		<-done
	}
}
