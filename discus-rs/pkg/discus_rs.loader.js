/**
 * discus_rs.loader.js — RTA-GUARD Streaming WASM Loader
 *
 * Uses WebAssembly.instantiateStreaming() for <200ms load time.
 * Falls back to fetch+instantiate for older browsers.
 *
 * Usage:
 *   import { loadDiscusRs } from './discus_rs.loader.js';
 *   const guard = await loadDiscusRs('./discus_rs_bg.wasm');
 *   const result = guard.check('user input here');
 */

/**
 * @typedef {Object} DiscusInstance
 * @property {function(string): string} check — Run all rules on input text
 * @property {function(string, string): string} check_input — Run rules with session ID
 * @property {function(): string} new_session — Create new session
 * @property {function(string): void} kill_session — Kill a session
 * @property {function(string): string} session_status — Get session status
 * @property {function(): string} hello — Module health check
 * @property {number} _loadTimeMs — WASM load time in milliseconds
 */

/**
 * Load the discus-rs WASM module via streaming instantiation.
 *
 * @param {string|URL|Response} source — WASM binary URL, or a Response object
 * @param {Object} [imports] — Optional WASM import overrides
 * @returns {Promise<DiscusInstance>}
 */
export async function loadDiscusRs(source, imports = {}) {
  const t0 = performance.now();

  // Default import object — wasm-bindgen uses these
  const defaultImports = {
    __wbindgen_placeholder__: {},
    ...imports,
  };

  let instance;
  let module;

  try {
    // Primary path: streaming instantiation (fastest — compile + instantiate parallel)
    if (typeof source === 'string' || source instanceof URL) {
      const response = await fetch(source);

      if (typeof WebAssembly.instantiateStreaming === 'function') {
        const result = await WebAssembly.instantiateStreaming(response, defaultImports);
        module = result.module;
        instance = result.instance;
      } else {
        // Fallback: fetch → arrayBuffer → instantiate
        const bytes = await response.arrayBuffer();
        const result = await WebAssembly.instantiate(bytes, defaultImports);
        module = result.module;
        instance = result.instance;
      }
    } else if (source instanceof Response) {
      // Response object passed directly
      if (typeof WebAssembly.instantiateStreaming === 'function') {
        const result = await WebAssembly.instantiateStreaming(source, defaultImports);
        module = result.module;
        instance = result.instance;
      } else {
        const bytes = await source.arrayBuffer();
        const result = await WebAssembly.instantiate(bytes, defaultImports);
        module = result.module;
        instance = result.instance;
      }
    } else if (source instanceof ArrayBuffer || source instanceof Uint8Array) {
      // Raw bytes
      const result = await WebAssembly.instantiate(source, defaultImports);
      module = result.module;
      instance = result.instance;
    } else {
      throw new Error('Invalid source type. Expected URL string, Response, or ArrayBuffer.');
    }
  } catch (err) {
    throw new Error(`[discus-rs] WASM load failed: ${err.message}`);
  }

  const loadTimeMs = performance.now() - t0;

  // Extract exports from wasm-bindgen module
  const exports = instance.exports;

  // wasm-bindgen wrapper: imports are attached to the module
  // The actual API is exposed through wasm-bindgen's generated JS glue
  // For raw instantiation, we export the raw functions

  /**
   * Wraps a wasm-bindgen exported function to handle string marshalling.
   * wasm-bindgen allocates strings in WASM memory; we need to pass/receive
   * pointers through the allocator functions.
   */
  function withString(str, fn) {
    const ptr = exports.__wbindgen_malloc(str.length, 1);
    const mem = new Uint8Array(exports.memory.buffer);
    for (let i = 0; i < str.length; i++) {
      mem[ptr + i] = str.charCodeAt(i);
    }
    const result = fn(ptr, str.length);
    return result;
  }

  // Build the public API surface
  const api = {
    /**
     * Run all 13 RTA rules against input text.
     * @param {string} input — Text to check
     * @returns {string} JSON result with {allowed, session_id, decision, results}
     */
    check(input) {
      if (exports.check) {
        return withString(input, exports.check);
      }
      // Fallback: call check_input with default session
      return api.check_input('default', input);
    },

    /**
     * Run rules with explicit session context.
     * @param {string} sessionId
     * @param {string} input
     * @returns {string} JSON result
     */
    check_input(sessionId, input) {
      if (exports.check_input) {
        // wasm-bindgen passes two strings: need to marshal both
        const ptr1 = exports.__wbindgen_malloc(sessionId.length, 1);
        const ptr2 = exports.__wbindgen_malloc(input.length, 1);
        const mem = new Uint8Array(exports.memory.buffer);
        for (let i = 0; i < sessionId.length; i++) mem[ptr1 + i] = sessionId.charCodeAt(i);
        for (let i = 0; i < input.length; i++) mem[ptr2 + i] = input.charCodeAt(i);
        return exports.check_input(ptr1, sessionId.length, ptr2, input.length);
      }
      throw new Error('check_input not exported');
    },

    /** Create a new guard session. */
    new_session() {
      if (exports.new_session) return exports.new_session();
      throw new Error('new_session not exported');
    },

    /** Kill a session by ID. */
    kill_session(sessionId) {
      if (exports.kill_session) {
        withString(sessionId, exports.kill_session);
      }
    },

    /** Check if a session is alive. */
    session_status(sessionId) {
      if (exports.session_status) {
        return withString(sessionId, exports.session_status);
      }
      throw new Error('session_status not exported');
    },

    /** Health check — returns module status string. */
    hello() {
      if (exports.hello) return exports.hello();
      return 'discus-rs module loaded';
    },

    /** @internal Raw WASM instance for advanced usage */
    _instance: instance,
    _module: module,
    _exports: exports,
    _loadTimeMs: loadTimeMs,
  };

  console.log(`[discus-rs] WASM loaded in ${loadTimeMs.toFixed(1)}ms`);
  return api;
}

/**
 * Convenience: load from default path relative to this script.
 * @returns {Promise<DiscusInstance>}
 */
export async function loadDiscusRsDefault() {
  // Try to resolve the .wasm file relative to the loader script
  const scriptUrl = import.meta?.url || '';
  const basePath = scriptUrl.replace(/[^/]+$/, '');
  return loadDiscusRs(basePath + 'discus_rs_bg.wasm');
}

// Default export
export default loadDiscusRs;
