/**
 * RTA-GUARD Discus — Browser Content Script
 *
 * Can be injected into any page. Monitors text inputs, intercepts
 * form submissions, shows visual warnings, and provides a floating widget.
 *
 * Usage:
 *   - As a browser extension content script (via manifest.json)
 *   - Or manually: <script src="discus-guard.js"></script>
 *
 * The script auto-loads discus_rs.wasm from the same directory.
 * Falls back to pure-JS detection if WASM fails to load.
 */

(function () {
  'use strict';

  // Prevent double-init
  if (window.__discusGuardLoaded) return;
  window.__discusGuardLoaded = true;

  const SESSION_ID = 'dg-' + Math.random().toString(36).substr(2, 9);
  let discus = null;
  let wasmReady = false;
  let panelOpen = false;
  let checkCount = 0;
  let violationCount = 0;
  let killedCount = 0;
  let lastViolations = [];
  let debounceTimers = new WeakMap();

  // ─── Inline styles (avoids CSS file dependency) ───

  const WIDGET_CSS = `
    #dg-widget{position:fixed;bottom:20px;right:20px;z-index:2147483647;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:13px;line-height:1.4;user-select:none}
    #dg-widget .dg-b{display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:20px;background:#1a1a2e;color:#e0e0e0;box-shadow:0 2px 12px rgba(0,0,0,.3);cursor:pointer;transition:all .2s;border:1px solid #333}
    #dg-widget .dg-b:hover{box-shadow:0 4px 20px rgba(0,0,0,.5);transform:translateY(-1px)}
    #dg-widget .dg-b.dg-ok{border-color:#2ecc71;background:#0d2818}
    #dg-widget .dg-b.dg-warn{border-color:#f39c12;background:#2d2a1a}
    #dg-widget .dg-b.dg-dead{border-color:#e74c3c;background:#2d1a1a}
    #dg-widget .dg-i{width:16px;height:16px;border-radius:50%;flex-shrink:0}
    #dg-widget .dg-i.dg-g{background:#2ecc71;box-shadow:0 0 6px #2ecc7188}
    #dg-widget .dg-i.dg-y{background:#f39c12;box-shadow:0 0 6px #f39c1288;animation:dg-p 1.5s ease-in-out infinite}
    #dg-widget .dg-i.dg-r{background:#e74c3c;box-shadow:0 0 6px #e74c3c88;animation:dg-p .8s ease-in-out infinite}
    @keyframes dg-p{0%,100%{opacity:1}50%{opacity:.5}}
    #dg-widget .dg-p{position:absolute;bottom:calc(100% + 8px);right:0;width:320px;background:#1a1a2e;border:1px solid #333;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.5);padding:16px;display:none}
    #dg-widget .dg-p.dg-o{display:block;animation:dg-fi .15s ease}
    @keyframes dg-fi{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
    #dg-widget .dg-p h3{margin:0 0 8px;color:#ff6b35;font-size:14px}
    #dg-widget .dg-s{display:flex;justify-content:space-between;padding:4px 0;color:#aaa;font-size:12px}
    #dg-widget .dg-sv{color:#e0e0e0;font-weight:600}
    #dg-widget .dg-vl{margin-top:8px;max-height:200px;overflow-y:auto}
    #dg-widget .dg-v{padding:6px 8px;margin:4px 0;border-radius:6px;font-size:11px;background:#0d0d0d;border-left:3px solid #e74c3c}
    #dg-widget .dg-v.dg-w{border-left-color:#f39c12}
    .dg-fw{outline:2px solid #e74c3c!important;outline-offset:2px;transition:outline-color .3s}
    .dg-fc{outline:2px solid #f39c12!important;outline-offset:2px;transition:outline-color .3s}
    .dg-t{position:fixed;top:20px;right:20px;z-index:2147483647;padding:12px 20px;border-radius:8px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:13px;color:#fff;box-shadow:0 4px 20px rgba(0,0,0,.4);animation:dg-si .3s ease,dg-fo .3s ease 3s forwards;pointer-events:none}
    .dg-tk{background:#c0392b;border:1px solid #e74c3c}
    .dg-tw{background:#7d6608;border:1px solid #f39c12}
    @keyframes dg-si{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:translateX(0)}}
    @keyframes dg-fo{from{opacity:1}to{opacity:0}}
  `;

  // ─── Inject CSS ───

  const style = document.createElement('style');
  style.textContent = WIDGET_CSS;
  (document.head || document.documentElement).appendChild(style);

  // ─── WASM Loading ───

  async function loadWasm() {
    try {
      // Try to find the WASM binary — check common locations
      const wasmUrls = [
        new URL('./discus_rs.wasm', import.meta?.url || location.href).href,
        chrome?.runtime?.getURL?.('discus_rs.wasm'),
        location.origin + '/discus_rs.wasm',
      ].filter(Boolean);

      // Also try dynamic import of the pkg module
      const pkgUrls = [
        new URL('./pkg/discus_rs.js', import.meta?.url || location.href).href,
        chrome?.runtime?.getURL?.('pkg/discus_rs.js'),
      ].filter(Boolean);

      for (const url of pkgUrls) {
        try {
          const mod = await import(url);
          await mod.init();
          discus = mod;
          wasmReady = true;
          console.log('[Discus-Guard] WASM loaded via ES module');
          return;
        } catch (e) {
          // Try next
        }
      }

      // If no module found, use inline fallback
      discus = createFallbackEngine();
      wasmReady = true;
      console.log('[Discus-Guard] Using fallback engine (no WASM available)');
    } catch (e) {
      console.warn('[Discus-Guard] WASM load failed, using fallback:', e.message);
      discus = createFallbackEngine();
      wasmReady = true;
    }
  }

  // ─── Fallback Engine (pure JS) ───

  function createFallbackEngine() {
    const killed = new Set();

    const PII = [
      /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g,
      /\b\d{3}[-.]?\d{3}[-.]?\d{4}\b/g,
      /\b\d{3}-\d{2}-\d{4}\b/g,
      /\b(?:\d{4}[-\s]?){3}\d{4}\b/g,
    ];

    const INJ = [
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

    const BLOCKED = ['hack', 'exploit', 'bypass security'];

    return {
      check(text, sessionId) {
        const sid = sessionId || SESSION_ID;
        if (killed.has(sid)) {
          return { killed: true, decision: 'KILL', violations: [], kill_reason: 'Session killed', session_id: sid };
        }

        const violations = [];

        for (const p of PII) {
          p.lastIndex = 0;
          if (p.test(text)) {
            violations.push({ rule_name: 'PII Detection', rule_id: 'pii', passed: false, severity: 'High', violation_type: 'PiiExposure', decision: 'KILL', confidence: 0.9, details: 'PII pattern detected' });
            break;
          }
        }

        for (const p of INJ) {
          if (p.test(text)) {
            violations.push({ rule_name: 'Injection Detection', rule_id: 'inject', passed: false, severity: 'Critical', violation_type: 'PromptInjection', decision: 'KILL', confidence: 0.85, details: 'Injection pattern detected' });
            break;
          }
        }

        const low = text.toLowerCase();
        for (const kw of BLOCKED) {
          if (low.includes(kw)) {
            violations.push({ rule_name: 'Blocked Keyword', rule_id: 'kw', passed: false, severity: 'Medium', violation_type: 'BlockedKeyword', decision: 'WARN', confidence: 0.8, details: `Blocked: "${kw}"` });
            break;
          }
        }

        const k = violations.some(v => v.decision === 'KILL');
        if (k) killed.add(sid);

        return { killed: k, decision: k ? 'KILL' : violations.length > 0 ? 'WARN' : 'PASS', violations, kill_reason: k ? 'Policy violation' : null, session_id: sid };
      },
      kill(sid) { const n = !killed.has(sid); killed.add(sid); return n; },
      isAlive(sid) { return !killed.has(sid); },
    };
  }

  // ─── Widget ───

  function createWidget() {
    const widget = document.createElement('div');
    widget.id = 'dg-widget';
    widget.innerHTML = `
      <div class="dg-p" id="dg-panel">
        <h3>🛡️ RTA-GUARD Discus</h3>
        <div class="dg-s"><span>Status</span><span class="dg-sv" id="dg-st">Initializing...</span></div>
        <div class="dg-s"><span>Checks</span><span class="dg-sv" id="dg-ck">0</span></div>
        <div class="dg-s"><span>Violations</span><span class="dg-sv" id="dg-vc">0</span></div>
        <div class="dg-s"><span>Killed</span><span class="dg-sv" id="dg-kc">0</span></div>
        <div class="dg-s"><span>Session</span><span class="dg-sv" id="dg-sid">${SESSION_ID}</span></div>
        <div class="dg-vl" id="dg-vl"></div>
      </div>
      <div class="dg-b dg-ok" id="dg-badge">
        <div class="dg-i dg-g" id="dg-dot"></div>
        <span class="dg-label">Discus</span>
      </div>
    `;

    document.body.appendChild(widget);

    document.getElementById('dg-badge').addEventListener('click', () => {
      panelOpen = !panelOpen;
      document.getElementById('dg-panel').className = 'dg-p' + (panelOpen ? ' dg-o' : '');
    });

    // Close panel on outside click
    document.addEventListener('click', (e) => {
      if (panelOpen && !widget.contains(e.target)) {
        panelOpen = false;
        document.getElementById('dg-panel').className = 'dg-p';
      }
    });
  }

  function updateWidget() {
    const st = document.getElementById('dg-st');
    const ck = document.getElementById('dg-ck');
    const vc = document.getElementById('dg-vc');
    const kc = document.getElementById('dg-kc');
    const dot = document.getElementById('dg-dot');
    const badge = document.getElementById('dg-badge');

    if (!st) return;

    ck.textContent = checkCount;
    vc.textContent = violationCount;
    kc.textContent = killedCount;

    if (killedCount > 0) {
      st.textContent = 'KILLED';
      dot.className = 'dg-i dg-r';
      badge.className = 'dg-b dg-dead';
    } else if (violationCount > 0) {
      st.textContent = 'WARNING';
      dot.className = 'dg-i dg-y';
      badge.className = 'dg-b dg-warn';
    } else {
      st.textContent = wasmReady ? 'ACTIVE' : 'LOADING';
      dot.className = 'dg-i dg-g';
      badge.className = 'dg-b dg-ok';
    }

    // Update violation list
    const vl = document.getElementById('dg-vl');
    if (vl && lastViolations.length > 0) {
      vl.innerHTML = lastViolations.slice(-10).map(v => `
        <div class="dg-v${v.decision === 'WARN' ? ' dg-w' : ''}">
          <div><strong>${v.severity}</strong> — ${v.rule_name || v.violation_type || 'Violation'}</div>
          <div style="color:#888;margin-top:2px">${v.details || ''}</div>
        </div>
      `).join('');
    }
  }

  // ─── Toast ───

  function showToast(message, type) {
    const toast = document.createElement('div');
    toast.className = `dg-t dg-t${type === 'KILL' ? 'k' : 'w'}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
  }

  // ─── Check Logic ───

  function performCheck(text, source) {
    if (!discus || !text || text.trim().length < 3) return null;

    checkCount++;
    const result = discus.check(text, SESSION_ID);

    if (result.violations && result.violations.length > 0) {
      violationCount += result.violations.length;
      lastViolations.push(...result.violations);

      if (result.killed) {
        killedCount++;
        showToast(`🛡️ Session killed: ${result.kill_reason || 'Policy violation'}`, 'KILL');
      } else {
        showToast(`⚠️ Warning: ${result.violations[0].rule_name || 'Violation detected'}`, 'WARN');
      }
    }

    updateWidget();
    return result;
  }

  // ─── Input Monitoring ───

  function getTextFromElement(el) {
    if (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && el.type === 'text')) {
      return el.value;
    }
    if (el.isContentEditable) {
      return el.innerText || el.textContent || '';
    }
    return '';
  }

  function handleInputEvent(e) {
    const el = e.target;
    if (!el || !el.tagName) return;

    const isTextInput =
      el.tagName === 'TEXTAREA' ||
      (el.tagName === 'INPUT' && ['text', 'search', 'url', 'email', ''].includes(el.type)) ||
      el.isContentEditable;

    if (!isTextInput) return;

    // Debounce: check after 500ms of no typing
    const existing = debounceTimers.get(el);
    if (existing) clearTimeout(existing);

    debounceTimers.set(el, setTimeout(() => {
      const text = getTextFromElement(el);
      if (text.length < 5) return;

      const result = performCheck(text, 'input');

      // Visual feedback on the field
      el.classList.remove('dg-fw', 'dg-fc');
      if (result) {
        if (result.killed) {
          el.classList.add('dg-fw');
        } else if (result.violations.length > 0) {
          el.classList.add('dg-fc');
        }
      }
    }, 500));
  }

  // ─── Form Submission Interception ───

  function handleFormSubmit(e) {
    const form = e.target;
    if (!form || form.tagName !== 'FORM') return;

    // Collect all text from form fields
    let allText = '';
    const fields = form.querySelectorAll('textarea, input[type="text"], input[type="search"], [contenteditable="true"]');
    fields.forEach(f => {
      const text = getTextFromElement(f);
      if (text) allText += text + '\n';
    });

    if (allText.trim().length < 3) return;

    const result = performCheck(allText, 'submit');

    if (result && result.killed) {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();

      // Highlight all fields
      fields.forEach(f => f.classList.add('dg-fw'));

      showToast('🛡️ Form submission blocked — session killed', 'KILL');
      console.warn('[Discus-Guard] Form submission blocked:', result.kill_reason);

      return false;
    }
  }

  // ─── Mutation Observer (for dynamic content) ───

  function observeNewInputs() {
    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;

          // Add input listener to new textareas/contenteditables
          const fields = node.querySelectorAll?.('textarea, [contenteditable="true"], input[type="text"], input[type="search"]') || [];
          if (fields.length > 0) {
            fields.forEach(f => f.addEventListener('input', handleInputEvent));
          }

          // Intercept new forms
          if (node.tagName === 'FORM') {
            node.addEventListener('submit', handleFormSubmit, true);
          }
          const forms = node.querySelectorAll?.('form') || [];
          forms.forEach(f => f.addEventListener('submit', handleFormSubmit, true));
        }
      }
    });

    observer.observe(document.body || document.documentElement, {
      childList: true,
      subtree: true,
    });
  }

  // ─── Initialization ───

  async function boot() {
    await loadWasm();

    // Create widget
    if (document.body) {
      createWidget();
      updateWidget();
    } else {
      document.addEventListener('DOMContentLoaded', () => {
        createWidget();
        updateWidget();
      });
    }

    // Attach listeners
    document.addEventListener('input', handleInputEvent, true);
    document.addEventListener('submit', handleFormSubmit, true);

    // Observe DOM for dynamically added elements
    if (typeof MutationObserver !== 'undefined') {
      if (document.body) {
        observeNewInputs();
      } else {
        document.addEventListener('DOMContentLoaded', observeNewInputs);
      }
    }

    console.log('[Discus-Guard] Initialized. Session:', SESSION_ID);
  }

  boot();

  // ─── Public API (for testing / manual use) ───

  window.__discusGuard = {
    check: (text) => performCheck(text, 'manual'),
    kill: (sid) => discus?.kill(sid || SESSION_ID),
    isAlive: (sid) => discus?.isAlive(sid || SESSION_ID),
    getSessionId: () => SESSION_ID,
    isReady: () => wasmReady,
    getStats: () => ({ checkCount, violationCount, killedCount }),
  };

})();
