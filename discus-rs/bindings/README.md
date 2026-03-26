# Multi-language Bindings for RTA-GUARD Discus

RTA-GUARD Discus provides a **deterministic AI session kill-switch** backed by Rust/WASM. This directory contains bindings for Python, JavaScript/TypeScript, Rust, Go, and C/C++.

## API Contract

All bindings expose the same 4 functions:

| Function | Signature | Description |
|----------|-----------|-------------|
| `check` | `(session_id, input) → CheckResult` | Evaluate input through RTA rules |
| `kill` | `(session_id) → void` | Terminate a session |
| `is_alive` | `(session_id) → bool` | Check if session is active |
| `get_rules` | `() → string[]` | List active rule names |

See [BINDING_SPEC.md](./BINDING_SPEC.md) for the full API contract.

---

## Python

**Install:**
```bash
pip install maturin
cd bindings/python
maturin develop --release
```

**Usage:**
```python
from discus_rs import check, kill, is_alive, get_rules

result = check("sess-001", "Hello, world!")
print(result)  # {"allowed": True, "session_id": "sess-001", ...}

kill("sess-001")
print(is_alive("sess-001"))  # False

rules = get_rules()
print(rules)  # ["SATYA", "DHARMA", "YAMA", ...]
```

**Run tests:**
```bash
cd bindings/python
python test_python_bindings.py -v
```

---

## JavaScript / TypeScript

**Install:**
```bash
npm i @rta-guard/discus
```

**Usage:**
```typescript
import { Discus } from '@rta-guard/discus';

const guard = await Discus.init();
const result = guard.check('sess-001', 'Hello, world!');
console.log(result); // { allowed: true, session_id: 'sess-001', ... }

guard.kill('sess-001');
console.log(guard.isAlive('sess-001')); // false

const rules = guard.getRules();
console.log(rules); // ['SATYA', 'DHARMA', ...]
```

**Run tests:**
```bash
cd bindings/js
npm install
npx tsx test/test_bindings.ts
```

---

## Rust

**Add dependency:**
```toml
[dependencies]
discus-bindings = { path = "discus-rs/bindings/rust" }
```

**Usage:**
```rust
use discus_bindings::Discus;

let mut guard = Discus::new();
let result = guard.check("sess-001", "Hello, world!");
println!("{:?}", result);

guard.kill("sess-001");
assert!(!guard.is_alive("sess-001"));

let rules = guard.get_rules();
println!("{:?}", rules);
```

**Run tests:**
```bash
cd discus-rs
cargo test -p discus-bindings
```

---

## Go

**Install:**
```bash
go get github.com/rta-guard/discus-go
```

**Usage:**
```go
import "github.com/rta-guard/discus-go"

guard, _ := discus.New()
result, _ := guard.Check("sess-001", "Hello, world!")
fmt.Println(result.Allowed) // true

guard.Kill("sess-001")
fmt.Println(guard.IsAlive("sess-001")) // false

rules := guard.GetRules()
fmt.Println(rules) // [SATYA DHARMA YAMA ...]
```

**Run tests:**
```bash
cd bindings/go
go test -v
```

---

## C / C++

**Build:**
```bash
cd bindings/c
make lib
```

**Usage:**
```c
#include <discus/discus.h>

int main() {
    discus_init(NULL);

    DiscusCheckResult result;
    discus_check("sess-001", "Hello, world!", &result);
    printf("allowed: %d, decision: %s\n", result.allowed, result.decision);
    discus_free_result(&result);

    discus_kill("sess-001");
    printf("alive: %d\n", discus_is_alive("sess-001")); // 0

    discus_shutdown();
    return 0;
}
```

**Run tests:**
```bash
cd bindings/c
make test
```

**Install system-wide:**
```bash
sudo make install
```

---

## Architecture

```
discus-rs/
├── src/              # Rust core (engine, rules, session, types)
├── bindings/
│   ├── python/       # PyO3 bindings (maturin)
│   │   ├── Cargo.toml
│   │   ├── pyproject.toml
│   │   ├── src/lib.rs
│   │   ├── __init__.py
│   │   └── test_python_bindings.py
│   ├── js/           # TypeScript + WASM bindings
│   │   ├── package.json
│   │   ├── src/index.ts
│   │   ├── src/types.ts
│   │   └── test/test_bindings.ts
│   ├── rust/         # Rust wrapper crate
│   │   ├── Cargo.toml
│   │   └── src/lib.rs
│   ├── go/           # Go bindings (wasmer-go fallback)
│   │   ├── go.mod
│   │   ├── discus.go
│   │   └── discus_test.go
│   ├── c/            # C bindings (wasmtime C API)
│   │   ├── discus.h
│   │   ├── discus.c
│   │   ├── test_discus.c
│   │   └── Makefile
│   ├── README.md     # This file
│   └── BINDING_SPEC.md  # API contract
└── target/           # WASM binaries
    ├── wasm32-unknown-unknown/    (browser)
    └── wasm32-wasip1/             (WASI)
```

## Versioning

All bindings are versioned in lockstep with `discus-rs` core (currently `0.1.0`).
