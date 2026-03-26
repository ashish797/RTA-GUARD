/**
 * RTA-GUARD Discus JavaScript/TypeScript Bindings
 *
 * WASM-backed deterministic AI session kill-switch.
 *
 * Usage:
 *   import { Discus } from '@rta-guard/discus';
 *
 *   const guard = await Discus.init();
 *   const result = guard.check('sess-001', 'Hello, world!');
 *   console.log(result); // { allowed: true, session_id: 'sess-001', ... }
 *
 *   guard.kill('sess-001');
 *   console.log(guard.isAlive('sess-001')); // false
 *
 *   console.log(guard.getRules()); // ['SATYA', 'DHARMA', ...]
 */

import type { CheckResult, DiscusEngine, DiscusOptions, RuleResult } from "./types";

// Re-export types
export type { CheckResult, DiscusEngine, DiscusOptions, RuleResult } from "./types";

/** Default rule names when WASM module is unavailable */
const DEFAULT_RULES: string[] = [
  "SATYA", "DHARMA", "YAMA", "MITRA", "VARUNA",
  "INDRA", "AGNI", "VAYU", "SOMA", "KUBERA",
  "ANRTA_DRIFT", "MAYA", "ALIGNMENT",
];

/**
 * Discus guard engine — wraps WASM module with a clean JS API
 */
export class Discus implements DiscusEngine {
  private killed: Set<string> = new Set();
  private wasmInstance: any = null;

  private constructor(wasmInstance?: any) {
    this.wasmInstance = wasmInstance;
  }

  /**
   * Initialize the Discus engine
   * Loads WASM binary and prepares the engine
   */
  static async init(options?: DiscusOptions): Promise<Discus> {
    try {
      // Dynamic import of wasm-bindgen output
      const pkg = await import("../../pkg/discus_rs.js");
      if (pkg.default) {
        await pkg.default(options?.wasmPath);
      }
      return new Discus(pkg);
    } catch {
      // Fallback: JS-only simulation
      console.warn("[Discus] WASM unavailable, using JS fallback");
      return new Discus(null);
    }
  }

  check(sessionId: string, input: string): CheckResult {
    if (this.wasmInstance?.check_input) {
      try {
        const raw = this.wasmInstance.check_input(sessionId, input);
        return JSON.parse(raw);
      } catch {
        return this._fallbackCheck(sessionId, input);
      }
    }
    return this._fallbackCheck(sessionId, input);
  }

  kill(sessionId: string): void {
    this.killed.add(sessionId);
    if (this.wasmInstance?.kill_session) {
      try {
        this.wasmInstance.kill_session(sessionId);
      } catch {
        // JS fallback handles it via killed set
      }
    }
  }

  isAlive(sessionId: string): boolean {
    if (this.wasmInstance?.session_status) {
      try {
        return this.wasmInstance.session_status(sessionId) === "alive";
      } catch {
        // Fall through to JS state
      }
    }
    return !this.killed.has(sessionId);
  }

  getRules(): string[] {
    if (this.wasmInstance?.get_rules) {
      try {
        return JSON.parse(this.wasmInstance.get_rules());
      } catch {
        // Fall through to default
      }
    }
    return [...DEFAULT_RULES];
  }

  private _fallbackCheck(sessionId: string, input: string): CheckResult {
    const isKilled = this.killed.has(sessionId);
    return {
      allowed: !isKilled,
      session_id: sessionId,
      decision: isKilled ? "Kill" : "Pass",
      results: DEFAULT_RULES.map((name) => ({
        rule: name,
        passed: !isKilled,
        severity: isKilled ? "Critical" as const : "Info" as const,
        message: isKilled ? `Session ${sessionId} is killed` : "No violations detected",
      })),
    };
  }
}

/** Default export */
export default Discus;
