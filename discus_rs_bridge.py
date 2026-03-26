"""
Discus-RS Bridge — Python interface to the Rust Wasm module.
Provides the same API as discus.guard.DiscusGuard but uses the Rust core.
"""

import json
import os
import subprocess
import sys
from typing import Dict, Any, Optional, List

class DiscusRsBridge:
    """Bridge to the Rust Discus implementation."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {
            "kill_on_pii": True,
            "kill_on_injection": True,
            "kill_on_jailbreak": True,
            "blocked_keywords": ["hack", "exploit", "bypass security"],
            "min_severity": "Medium",
            "confidence_threshold": 0.7
        }
        self.config_json = json.dumps(self.config)
    
    def check(self, text: str, session_id: str = "default") -> Dict[str, Any]:
        """Check text against Rust implementation."""
        input_json = json.dumps({"text": text, "session_id": session_id})
        
        # For now, use subprocess to call Rust binary
        # In future, use wasmtime or pyo3
        result = self._call_rust(input_json)
        return result
    
    def check_text(self, text: str) -> Dict[str, Any]:
        """Check text without session tracking."""
        return self.check(text, "no-session")
    
    def _call_rust(self, input_json: str) -> Dict[str, Any]:
        """Call Rust binary via subprocess."""
        discus_rs_dir = os.path.join(os.path.dirname(__file__), "discus-rs")
        lib_path = os.path.join(discus_rs_dir, "target", "debug", "libdiscus_rs.so")
        
        if not os.path.exists(lib_path):
            # Fallback: use Python implementation
            return self._python_fallback(json.loads(input_json)["text"])
        
        # TODO: Use ctypes or wasmtime to load .so/.wasm
        # For now, fallback to Python
        return self._python_fallback(json.loads(input_json)["text"])
    
    def _python_fallback(self, text: str) -> Dict[str, Any]:
        """Python fallback when Rust module isn't loaded."""
        from discus.guard import DiscusGuard as PyGuard
        
        guard = PyGuard(config=self.config)
        result = guard.check_text(text)
        
        return {
            "killed": result.killed if hasattr(result, 'killed') else False,
            "decision": str(result.decision) if hasattr(result, 'decision') else "PASS",
            "violations": [],
            "kill_reason": getattr(result, 'kill_reason', None),
            "session_id": "",
            "timestamp": str(result.timestamp) if hasattr(result, 'timestamp') else ""
        }
