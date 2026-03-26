#!/usr/bin/env bash
set -euo pipefail

# RTA-GUARD — discus-rs build script
# Builds native + WASM binary, reports sizes.
# Idempotent: safe to run multiple times.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${CYAN}[build]${NC} $1"; }
ok()  { echo -e "${GREEN}[  ok ]${NC} $1"; }
warn(){ echo -e "${YELLOW}[ warn]${NC} $1"; }
err() { echo -e "${RED}[ err ]${NC} $1"; }

# ── Toolchain check ──────────────────────────────────────────────
log "Checking toolchain..."

if ! command -v cargo &>/dev/null; then
    err "cargo not found. Install Rust: https://rustup.rs"
    exit 1
fi
if ! command -v rustc &>/dev/null; then
    err "rustc not found. Install Rust: https://rustup.rs"
    exit 1
fi

RUST_VERSION=$(rustc --version | awk '{print $2}')
CARGO_VERSION=$(cargo --version | awk '{print $2}')
ok "rustc $RUST_VERSION, cargo $CARGO_VERSION"

# Check wasm32-unknown-unknown target
if ! rustup target list --installed 2>/dev/null | grep -q wasm32-unknown-unknown; then
    log "Adding wasm32-unknown-unknown target..."
    rustup target add wasm32-unknown-unknown
fi
ok "wasm32-unknown-unknown target available"

# ── Native build (tests) ─────────────────────────────────────────
log "Building native (debug) and running tests..."
cargo test 2>&1
ok "Native tests passed"

# ── WASM build ───────────────────────────────────────────────────
log "Building WASM release..."
BUILD_START=$(date +%s)

cargo build --target wasm32-unknown-unknown --release 2>&1

BUILD_END=$(date +%s)
BUILD_TIME=$((BUILD_END - BUILD_START))

WASM_FILE="target/wasm32-unknown-unknown/release/discus_rs.wasm"
if [ ! -f "$WASM_FILE" ]; then
    err "WASM binary not found at $WASM_FILE"
    exit 1
fi

WASM_SIZE=$(stat -c%s "$WASM_FILE" 2>/dev/null || stat -f%z "$WASM_FILE" 2>/dev/null)
WASM_SIZE_KB=$((WASM_SIZE / 1024))
WASM_SIZE_MB=$(echo "scale=2; $WASM_SIZE / 1048576" | bc 2>/dev/null || echo "$((WASM_SIZE_KB / 1024))")

ok "WASM binary: $WASM_FILE"
echo ""
echo "┌────────────────────────────────────────────┐"
echo "│  RTA-GUARD discus-rs Build Report          │"
echo "├────────────────────────────────────────────┤"
echo "│  Rust version:    $RUST_VERSION"
echo "│  WASM size:       ${WASM_SIZE_KB} KB (${WASM_SIZE_MB} MB)"
echo "│  Build time:      ${BUILD_TIME}s"
echo "│  Target:          wasm32-unknown-unknown"
echo "│  Profile:         release (opt-level=s, LTO)"
echo "├────────────────────────────────────────────┤"
if [ "$WASM_SIZE" -lt 2097152 ]; then
    echo "│  Status:          ✅ UNDER 2MB TARGET      │"
else
    echo "│  Status:          ⚠️  OVER 2MB TARGET       │"
fi
echo "└────────────────────────────────────────────┘"
echo ""

ok "Build complete."
