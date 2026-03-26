/**
 * RTA-GUARD Discus — TypeScript Declarations
 */

export interface RuleResult {
  rule_name: string;
  rule_id: string;
  passed: boolean;
  severity: 'Low' | 'Medium' | 'High' | 'Critical';
  violation_type: string | null;
  decision: 'KILL' | 'WARN' | 'PASS';
  confidence: number;
  details: string;
}

export interface CheckResult {
  killed: boolean;
  decision: 'KILL' | 'WARN' | 'PASS';
  violations: RuleResult[];
  kill_reason: string | null;
  session_id: string;
}

/**
 * Initialize the WASM module.
 * @param wasmUrl - Optional URL to the .wasm file
 */
export function init(wasmUrl?: string): Promise<void>;

/**
 * Check text for policy violations.
 * @param text - The text to analyze
 * @param sessionId - Session identifier
 */
export function check(text: string, sessionId?: string): CheckResult;

/**
 * Kill a session.
 * @param sessionId - Session to kill
 * @returns Whether the session was newly killed
 */
export function kill(sessionId: string): boolean;

/**
 * Check if a session is alive (not killed).
 * @param sessionId - Session to check
 */
export function isAlive(sessionId: string): boolean;

declare const _default: {
  init: typeof init;
  check: typeof check;
  kill: typeof kill;
  isAlive: typeof isAlive;
};
export default _default;
