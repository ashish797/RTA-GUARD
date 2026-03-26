/**
 * RTA-GUARD Discus — WASM JavaScript Bindings
 *
 * ES module that loads the discus_rs.wasm binary and exposes
 * check(text, sessionId), kill(sessionId), isAlive(sessionId).
 *
 * Uses the raw wasm-bindgen ABI: strings are passed via
 * __wbindgen_malloc / __wbindgen_free in WASM linear memory.
 */

let wasmInstance = null;
let wasmMemory = null;
let cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: false });
let cachedTextEncoder = new TextEncoder('utf-8');
let cachedUint8Memory = null;
let cachedInt32Memory = null;
let WASM_VECTOR_LEN = 0;

function getUint8Memory() {
  if (cachedUint8Memory === null || cachedUint8Memory.byteLength === 0) {
    cachedUint8Memory = new Uint8Array(wasmMemory.buffer);
  }
  return cachedUint8Memory;
}

function getInt32Memory() {
  if (cachedInt32Memory === null || cachedInt32Memory.byteLength === 0) {
    cachedInt32Memory = new Int32Array(wasmMemory.buffer);
  }
  return cachedInt32Memory;
}

function getStringFromWasm(ptr, len) {
  return cachedTextDecoder.decode(getUint8Memory().subarray(ptr, ptr + len));
}

function passStringToWasm(arg) {
  const buf = cachedTextEncoder.encode(arg);
  const ptr = wasmInstance.exports.__wbindgen_malloc(buf.length, 1);
  getUint8Memory().set(buf, ptr);
  WASM_VECTOR_LEN = buf.length;
  return ptr;
}

// Cached session handle (discussession_new returns handle via wasm-bindgen convention)
let _sessionHandle = null;

/**
 * Initialize the WASM module.
 * @param {string|undefined} wasmUrl - URL to the .wasm file. Defaults to discus_rs.wasm next to this script.
 * @returns {Promise<void>}
 */
export async function init(wasmUrl) {
  if (wasmInstance) return; // Already initialized

  const url = wasmUrl || new URL('./discus_rs.wasm', import.meta.url).href;

  let imports = {};

  // Provide the imports that wasm-bindgen expects
  imports.__wbindgen_placeholder__ = {
    __wbindgen_throw: function (ptr, len) {
      throw new Error(getStringFromWasm(ptr, len));
    },
    __wbindgen_rethrow: function (idx) {
      throw undefined; // Placeholder
    },
  };

  // env imports for wasm-bindgen
  imports.env = imports.env || {};

  // Provide console.log import
  if (typeof console !== 'undefined') {
    imports.env.console_log = function (ptr, len) {
      console.log(getStringFromWasm(ptr, len));
    };
  }

  // Fetch and instantiate
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch WASM: ${response.status} ${response.statusText}`);
  }

  const bytes = await response.arrayBuffer();
  const result = await WebAssembly.instantiate(bytes, imports);

  wasmInstance = result.instance;
  wasmMemory = wasmInstance.exports.memory;

  // Invalidate caches
  cachedUint8Memory = null;
  cachedInt32Memory = null;

  // Call init() to set up panic hook
  if (wasmInstance.exports.init) {
    try {
      wasmInstance.exports.init();
    } catch (e) {
      // init may throw if wasm-bindgen externref table isn't set up; that's ok
    }
  }

  // Create a session using discussession_new with default config
  const defaultConfig = JSON.stringify({
    kill_on_pii: true,
    kill_on_injection: true,
    kill_on_jailbreak: true,
    blocked_keywords: ['hack', 'exploit', 'bypass security'],
    min_severity: 'Medium',
    confidence_threshold: 0.7,
  });

  try {
    const configPtr = passStringToWasm(defaultConfig);
    const retptr = wasmInstance.exports.__wbindgen_add_to_stack_pointer(-16);
    wasmInstance.exports.discussession_new(retptr, configPtr, WASM_VECTOR_LEN);
    const r0 = getInt32Memory()[retptr / 4];
    const r1 = getInt32Memory()[retptr / 4 + 1];
    const r2 = getInt32Memory()[retptr / 4 + 2];
    wasmInstance.exports.__wbindgen_add_to_stack_pointer(16);

    if (r2) {
      // Error case
      const errMsg = getStringFromWasm(r0, r1);
      wasmInstance.exports.__wbindgen_free(r0, r1, 1);
      throw new Error(`Session creation failed: ${errMsg}`);
    }
    _sessionHandle = r0;
  } catch (e) {
    console.warn('[Discus] Session creation via WASM failed, using fallback mode:', e.message);
    _sessionHandle = null;
  }
}

/**
 * Check text for policy violations.
 * @param {string} text - The text to analyze
 * @param {string} sessionId - Session identifier
 * @returns {object} Result with { killed, decision, violations, kill_reason, session_id }
 */
export function check(text, sessionId) {
  if (!wasmInstance || !wasmMemory) {
    throw new Error('Discus WASM not initialized. Call init() first.');
  }

  if (_sessionHandle === null) {
    // Fallback: pure JS check
    return fallbackCheck(text, sessionId);
  }

  try {
    const input = JSON.stringify({ text, session_id: sessionId || 'default' });
    const inputPtr = passStringToWasm(input);
    const retptr = wasmInstance.exports.__wbindgen_add_to_stack_pointer(-16);

    wasmInstance.exports.discussession_check(retptr, _sessionHandle, inputPtr, WASM_VECTOR_LEN);

    const r0 = getInt32Memory()[retptr / 4];
    const r1 = getInt32Memory()[retptr / 4 + 1];
    const r2 = getInt32Memory()[retptr / 4 + 2];
    wasmInstance.exports.__wbindgen_add_to_stack_pointer(16);

    if (r2) {
      // Error — session killed or check failed
      const errMsg = getStringFromWasm(r0, r1);
      wasmInstance.exports.__wbindgen_free(r0, r1, 1);
      return {
        killed: true,
        decision: 'KILL',
        violations: [],
        kill_reason: errMsg,
        session_id: sessionId || 'default',
      };
    }

    const resultStr = getStringFromWasm(r0, r1);
    wasmInstance.exports.__wbindgen_free(r0, r1, 1);
    return JSON.parse(resultStr);
  } catch (e) {
    return fallbackCheck(text, sessionId);
  }
}

/**
 * Kill a session.
 * @param {string} sessionId - Session to kill
 * @returns {boolean} Whether the session was newly killed
 */
export function kill(sessionId) {
  if (!wasmInstance || !wasmMemory) {
    throw new Error('Discus WASM not initialized. Call init() first.');
  }

  if (_sessionHandle === null) {
    if (!window._discusKilled) window._discusKilled = new Set();
    const wasNew = !window._discusKilled.has(sessionId);
    window._discusKilled.add(sessionId);
    return wasNew;
  }

  try {
    const sidPtr = passStringToWasm(sessionId);
    const result = wasmInstance.exports.discussession_kill(_sessionHandle, sidPtr, WASM_VECTOR_LEN);
    return result !== 0;
  } catch (e) {
    return false;
  }
}

/**
 * Check if a session is alive (not killed).
 * @param {string} sessionId - Session to check
 * @returns {boolean} Whether the session is alive
 */
export function isAlive(sessionId) {
  if (!wasmInstance || !wasmMemory) {
    throw new Error('Discus WASM not initialized. Call init() first.');
  }

  if (_sessionHandle === null) {
    if (!window._discusKilled) window._discusKilled = new Set();
    return !window._discusKilled.has(sessionId);
  }

  try {
    const sidPtr = passStringToWasm(sessionId);
    const result = wasmInstance.exports.discussession_is_alive(_sessionHandle, sidPtr, WASM_VECTOR_LEN);
    return result !== 0;
  } catch (e) {
    return false;
  }
}

// ─── Fallback pure-JS implementation ───

const PII_PATTERNS = [
  /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g,          // email
  /\b\d{3}[-.]?\d{3}[-.]?\d{4}\b/g,                                    // phone (US)
  /\b\d{3}-\d{2}-\d{4}\b/g,                                            // SSN
  /\b(?:\d{4}[-\s]?){3}\d{4}\b/g,                                      // credit card
  /\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b/g, // IP
];

const INJECTION_PATTERNS = [
  /ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?|rules?)/i,
  /you\s+are\s+now\s+(?:a|an|the)/i,
  /forget\s+(?:everything|all|your)\s+(?:above|before|previous)/i,
  /system\s*:\s*/i,
  /\[INST\]/i,
  /<<SYS>>/i,
  /<\|im_start\|>/i,
  /jailbreak/i,
  /DAN\s+mode/i,
];

const BLOCKED_KEYWORDS = ['hack', 'exploit', 'bypass security'];

let _killedSessions = new Set();

function fallbackCheck(text, sessionId) {
  const sid = sessionId || 'default';

  if (_killedSessions.has(sid)) {
    return {
      killed: true,
      decision: 'KILL',
      violations: [],
      kill_reason: 'Session already killed',
      session_id: sid,
    };
  }

  const violations = [];

  // PII check
  for (const pattern of PII_PATTERNS) {
    pattern.lastIndex = 0;
    const match = pattern.exec(text);
    if (match) {
      violations.push({
        rule_name: 'PII Detection',
        rule_id: 'pii_001',
        passed: false,
        severity: 'High',
        violation_type: 'PiiExposure',
        decision: 'KILL',
        confidence: 0.9,
        details: `PII detected: ${match[0].substring(0, 20)}...`,
      });
      break;
    }
  }

  // Injection check
  for (const pattern of INJECTION_PATTERNS) {
    if (pattern.test(text)) {
      violations.push({
        rule_name: 'Prompt Injection',
        rule_id: 'inject_001',
        passed: false,
        severity: 'Critical',
        violation_type: 'PromptInjection',
        decision: 'KILL',
        confidence: 0.85,
        details: 'Prompt injection pattern detected',
      });
      break;
    }
  }

  // Blocked keywords
  const lowerText = text.toLowerCase();
  for (const kw of BLOCKED_KEYWORDS) {
    if (lowerText.includes(kw)) {
      violations.push({
        rule_name: 'Blocked Keyword',
        rule_id: 'kw_001',
        passed: false,
        severity: 'Medium',
        violation_type: 'BlockedKeyword',
        decision: 'WARN',
        confidence: 0.8,
        details: `Blocked keyword: "${kw}"`,
      });
      break;
    }
  }

  const killed = violations.some(v => v.decision === 'KILL');
  if (killed) _killedSessions.add(sid);

  return {
    killed,
    decision: killed ? 'KILL' : violations.length > 0 ? 'WARN' : 'PASS',
    violations,
    kill_reason: killed ? 'Policy violation detected' : null,
    session_id: sid,
  };
}

// Default export for convenience
export default { init, check, kill, isAlive };
