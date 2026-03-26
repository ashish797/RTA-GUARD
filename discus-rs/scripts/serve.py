#!/usr/bin/env python3
"""
RTA-GUARD — discus-rs WASM dev server
Serves the WASM binary with correct MIME type and CORS headers.
Usage: python3 scripts/serve.py [--port 8080] [--dir target/wasm32-unknown-unknown/release]
"""

import argparse
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler


class WasmHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves .wasm files with correct MIME type and CORS."""

    def __init__(self, *args, directory=None, **kwargs):
        self._wasm_dir = directory or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "target", "wasm32-unknown-unknown", "release"
        )
        super().__init__(*args, directory=self._wasm_dir, **kwargs)

    def end_headers(self):
        # CORS headers for browser testing
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Cache control for dev
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def guess_type(self, path):
        """Override MIME type for .wasm files."""
        if path.endswith(".wasm"):
            return "application/wasm"
        if path.endswith(".js"):
            return "application/javascript"
        return super().guess_type(path)

    def log_message(self, format, *args):
        sys.stderr.write(f"[serve] {args[0]}\n")


def main():
    parser = argparse.ArgumentParser(description="RTA-GUARD WASM dev server")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--dir", type=str, default=None,
                        help="Directory to serve (default: release build dir)")
    parser.add_argument("--bind", type=str, default="0.0.0.0", help="Bind address")
    args = parser.parse_args()

    handler_kwargs = {}
    if args.dir:
        handler_kwargs["directory"] = args.dir

    server = HTTPServer((args.bind, args.port), lambda *a: WasmHandler(*a, **handler_kwargs))

    print(f"🔧 RTA-GUARD WASM server")
    print(f"   Serving: {handler_kwargs.get('directory', 'default (release build dir)')}")
    print(f"   URL:     http://{args.bind}:{args.port}/")
    print(f"   WASM:    http://{args.bind}:{args.port}/discus_rs.wasm")
    print(f"   CORS:    enabled (all origins)")
    print(f"   Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
