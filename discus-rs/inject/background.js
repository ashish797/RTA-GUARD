/**
 * RTA-GUARD Discus — Background Service Worker (Manifest V3)
 *
 * Handles communication between content scripts and WASM module,
 * manages session state, and provides API for extension popup.
 */

// ─── Session State ───

const sessions = new Map(); // sessionId -> { created, checks, violations, killed }
const killedSessions = new Set();
let totalChecks = 0;
let totalViolations = 0;
let wasmReady = false;

// ─── Fallback Engine (same rules as content script) ───

const PII_PATTERNS = [
  /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g,
  /\b\d{3}[-.]?\d{3}[-.]?\d{4}\b/g,
  /\b\d{3}-\d{2}-\d{4}\b/g,
  /\b(?:\d{4}[-\s]?){3}\d{4}\b/g,
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

function fallbackCheck(text, sessionId) {
  if (killedSessions.has(sessionId)) {
    return {
      killed: true, decision: 'KILL', violations: [],
      kill_reason: 'Session already killed', session_id: sessionId,
    };
  }

  const violations = [];

  for (const p of PII_PATTERNS) {
    p.lastIndex = 0;
    if (p.test(text)) {
      violations.push({ rule_name: 'PII Detection', rule_id: 'pii', passed: false, severity: 'High', violation_type: 'PiiExposure', decision: 'KILL', confidence: 0.9, details: 'PII detected' });
      break;
    }
  }

  for (const p of INJECTION_PATTERNS) {
    if (p.test(text)) {
      violations.push({ rule_name: 'Injection Detection', rule_id: 'inject', passed: false, severity: 'Critical', violation_type: 'PromptInjection', decision: 'KILL', confidence: 0.85, details: 'Injection pattern' });
      break;
    }
  }

  const low = text.toLowerCase();
  for (const kw of BLOCKED_KEYWORDS) {
    if (low.includes(kw)) {
      violations.push({ rule_name: 'Blocked Keyword', rule_id: 'kw', passed: false, severity: 'Medium', violation_type: 'BlockedKeyword', decision: 'WARN', confidence: 0.8, details: `Blocked: "${kw}"` });
      break;
    }
  }

  const killed = violations.some(v => v.decision === 'KILL');
  if (killed) killedSessions.add(sessionId);

  return {
    killed,
    decision: killed ? 'KILL' : violations.length > 0 ? 'WARN' : 'PASS',
    violations,
    kill_reason: killed ? 'Policy violation' : null,
    session_id: sessionId,
  };
}

// ─── WASM Loading (attempt) ───

async function tryLoadWasm() {
  try {
    const url = chrome.runtime.getURL('pkg/discus_rs.wasm');
    const resp = await fetch(url);
    if (!resp.ok) return;

    const bytes = await resp.arrayBuffer();
    const result = await WebAssembly.instantiate(bytes, {});
    console.log('[Discus BG] WASM loaded, exports:', Object.keys(result.instance.exports).length);
    wasmReady = true;
  } catch (e) {
    console.log('[Discus BG] WASM not available, using fallback engine');
    wasmReady = false;
  }
}

// ─── Message Handler ───

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const { action, payload } = message;

  switch (action) {
    case 'check': {
      const { text, sessionId } = payload;
      const sid = sessionId || `ext-${sender.tab?.id || 'popup'}`;

      if (!sessions.has(sid)) {
        sessions.set(sid, { created: Date.now(), checks: 0, violations: 0 });
      }
      const session = sessions.get(sid);
      session.checks++;
      totalChecks++;

      const result = fallbackCheck(text, sid);

      if (result.violations.length > 0) {
        session.violations += result.violations.length;
        totalViolations += result.violations.length;
      }

      sendResponse(result);
      return true;
    }

    case 'kill': {
      const { sessionId } = payload;
      const wasNew = !killedSessions.has(sessionId);
      killedSessions.add(sessionId);
      sendResponse({ success: true, wasNew });
      return true;
    }

    case 'isAlive': {
      const { sessionId } = payload;
      sendResponse({ alive: !killedSessions.has(sessionId) });
      return true;
    }

    case 'reset': {
      const { sessionId } = payload;
      killedSessions.delete(sessionId);
      sessions.delete(sessionId);
      sendResponse({ success: true });
      return true;
    }

    case 'stats': {
      sendResponse({
        wasmReady,
        totalChecks,
        totalViolations,
        sessions: Object.fromEntries(
          Array.from(sessions.entries()).map(([k, v]) => [k, v])
        ),
        killedSessions: Array.from(killedSessions),
      });
      return true;
    }

    case 'health': {
      sendResponse({
        status: 'ok',
        engine: wasmReady ? 'wasm' : 'fallback',
        uptime: Date.now(),
      });
      return true;
    }

    default:
      sendResponse({ error: `Unknown action: ${action}` });
      return true;
  }
});

// ─── Lifecycle ───

chrome.runtime.onInstalled.addListener(() => {
  console.log('[Discus BG] Extension installed/updated');
  tryLoadWasm();
});

// Load WASM on service worker start
tryLoadWasm();
