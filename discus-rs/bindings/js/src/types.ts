/**
 * TypeScript interfaces for RTA-GUARD Discus bindings.
 */

/** Result of a check() call */
export interface CheckResult {
  /** Whether the input is allowed (no critical violations) */
  allowed: boolean;
  /** The session ID that was checked */
  session_id: string;
  /** Decision string: "Pass", "Warn", or "Kill" */
  decision: string;
  /** Individual rule evaluation results */
  results: RuleResult[];
}

/** Single rule evaluation result */
export interface RuleResult {
  /** Rule name (e.g., "SATYA", "DHARMA") */
  rule: string;
  /** Whether this rule passed */
  passed: boolean;
  /** Severity level */
  severity: Severity;
  /** Human-readable message */
  message: string;
}

/** Severity levels */
export type Severity = "Critical" | "Warning" | "Info";

/** Discus engine interface */
export interface DiscusEngine {
  /**
   * Evaluate input through the RTA rules engine
   * @param sessionId - Unique session identifier
   * @param input - Text content to evaluate
   */
  check(sessionId: string, input: string): CheckResult;

  /**
   * Kill a session — after this, isAlive returns false
   * @param sessionId - Session to kill
   */
  kill(sessionId: string): void;

  /**
   * Check if a session is currently active
   * @param sessionId - Session to check
   */
  isAlive(sessionId: string): boolean;

  /**
   * Get list of active rule names
   */
  getRules(): string[];
}

/** WASM module initialization options */
export interface DiscusOptions {
  /** Path to WASM binary (default: auto-detect) */
  wasmPath?: string;
  /** Whether to use WASI runtime (default: false, use wasm-bindgen) */
  useWasi?: boolean;
}
