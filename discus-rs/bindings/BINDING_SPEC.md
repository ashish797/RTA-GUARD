# BINDING_SPEC.md — RTA-GUARD Discus API Contract

## Canonical API Surface

Every language binding MUST expose these four functions with equivalent semantics:

### `check(session_id: string, input: string) -> CheckResult`

Evaluates `input` through the RTA rules engine for the given `session_id`.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Unique session identifier |
| `input` | string | Text content to evaluate |

**Returns:** `CheckResult` (JSON-serializable object)
```json
{
  "allowed": true,
  "session_id": "sess-001",
  "decision": "Pass",
  "results": [
    {
      "rule": "SATYA",
      "passed": true,
      "severity": "Info",
      "message": "No violations detected"
    }
  ]
}
```

### `kill(session_id: string) -> void`

Kills a session. After this call, `is_alive(session_id)` MUST return `false`.

### `is_alive(session_id: string) -> boolean`

Returns whether the session is currently active (not killed).

### `get_rules() -> string[]`

Returns the list of active rule names (e.g., `["SATYA", "DHARMA", "YAMA", ...]`).

---

## Error Handling

| Error Type | Behavior |
|-----------|----------|
| Invalid UTF-8 | Return error / throw exception |
| Empty session_id | Accept (use "default") |
| Session not found | `check` creates implicitly; `kill` returns success; `is_alive` returns `true` |

## Serialization

- All complex return types MUST be JSON-serializable
- Rule names: uppercase Sanskrit names (SATYA, DHARMA, YAMA, MITRA, VARUNA, etc.)
- Severities: `Critical`, `Warning`, `Info`
- Decisions: `Pass`, `Warn`, `Kill`

## Language-Specific Notes

| Language | Package Name | Install Method | WASM Runtime |
|----------|-------------|----------------|--------------|
| Python | `discus-rs` | `pip install discus-rs` | wasmtime via wasmer-py |
| JavaScript | `@rta-guard/discus` | `npm i @rta-guard/discus` | wasm-bindgen (browser) |
| Rust | `discus-bindings` | Cargo dependency | Native (re-export) |
| Go | `github.com/rta-guard/discus-go` | `go get` | wasmer-go |
| C/C++ | `libdiscus` | `make install` | wasmtime C API |

## Versioning

- Bindings version = discus-rs core version (semver)
- Breaking changes require major version bump
- New rules added as minor version bump
