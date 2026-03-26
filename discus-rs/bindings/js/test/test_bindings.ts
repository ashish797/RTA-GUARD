/**
 * Unit tests for @rta-guard/discus TypeScript bindings.
 *
 * Run with: npx tsx test/test_bindings.ts
 */

import { Discus } from "../src/index";
import type { CheckResult } from "../src/types";

let passed = 0;
let failed = 0;

function assert(condition: boolean, message: string) {
  if (condition) {
    passed++;
    console.log(`  ✓ ${message}`);
  } else {
    failed++;
    console.error(`  ✗ ${message}`);
  }
}

async function runTests() {
  console.log("\n=== @rta-guard/discus Bindings Tests ===\n");

  // Initialize
  const guard = await Discus.init();
  assert(guard !== null, "Discus.init() returns instance");

  // Test check()
  console.log("\n--- check() ---");
  const result: CheckResult = guard.check("test-session", "Hello, world!");
  assert(typeof result === "object", "check() returns object");
  assert(typeof result.allowed === "boolean", "result.allowed is boolean");
  assert(result.session_id === "test-session", "session_id preserved");
  assert(typeof result.decision === "string", "decision is string");
  assert(Array.isArray(result.results), "results is array");
  assert(result.results.length > 0, "results not empty");
  assert(typeof result.results[0].rule === "string", "rule name is string");
  assert(typeof result.results[0].passed === "boolean", "passed is boolean");

  // Test kill()
  console.log("\n--- kill() ---");
  guard.kill("kill-test");
  assert(!guard.isAlive("kill-test"), "killed session is not alive");

  // Test isAlive()
  console.log("\n--- isAlive() ---");
  assert(guard.isAlive("unknown-session"), "unknown session is alive");
  assert(!guard.isAlive("kill-test"), "killed session returns false");

  // Test getRules()
  console.log("\n--- getRules() ---");
  const rules = guard.getRules();
  assert(Array.isArray(rules), "getRules() returns array");
  assert(rules.length > 0, "rules not empty");
  assert(rules.includes("SATYA"), "includes SATYA");
  assert(rules.includes("DHARMA"), "includes DHARMA");
  assert(rules.includes("YAMA"), "includes YAMA");

  // Test full workflow
  console.log("\n--- workflow ---");
  const wf = guard.check("wf-session", "test");
  assert(wf.allowed === true, "fresh session is allowed");
  guard.kill("wf-session");
  const killed = guard.check("wf-session", "test");
  assert(killed.allowed === false, "killed session not allowed");
  assert(killed.decision === "Kill", "killed session decision is Kill");

  // Summary
  console.log(`\n=== Results: ${passed} passed, ${failed} failed ===\n`);
  if (failed > 0) process.exit(1);
}

runTests().catch((e) => {
  console.error("Test error:", e);
  process.exit(1);
});
