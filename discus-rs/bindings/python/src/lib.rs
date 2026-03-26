//! Python bindings for discus-rs via PyO3
//!
//! Exposes the same 4-function API: check, kill, is_alive, get_rules

use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3::exceptions::PyRuntimeError;

/// Check input text through the RTA engine
#[pyfunction]
fn check(py: Python<'_>, session_id: &str, input: &str) -> PyResult<PyObject> {
    let engine = discus_rs::RtaEngine::new(None);
    let ctx = discus_rs::RtaContext::builder(session_id, input).build();
    let (allowed, results, decision) = engine.check(&ctx);

    let dict = PyDict::new(py);
    dict.set_item("allowed", allowed)?;
    dict.set_item("session_id", session_id)?;
    dict.set_item("decision", format!("{:?}", decision))?;

    let results_json = serde_json::to_string(&results)
        .map_err(|e| PyRuntimeError::new_err(format!("Serialization error: {}", e)))?;
    // Import json module and parse
    let json_mod = py.import("json")?;
    let parsed = json_mod.call_method1("loads", (results_json,))?;
    dict.set_item("results", parsed)?;

    Ok(dict.into())
}

/// Kill a session by ID
#[pyfunction]
fn kill(session_id: &str) -> PyResult<()> {
    let mut sm = discus_rs::SessionManager::new();
    sm.kill_session(session_id, "killed via Python binding");
    Ok(())
}

/// Check if a session is alive
#[pyfunction]
fn is_alive(session_id: &str) -> bool {
    let sm = discus_rs::SessionManager::new();
    sm.is_alive(session_id)
}

/// Get list of active rule names
#[pyfunction]
fn get_rules(_py: Python<'_>) -> Vec<String> {
    let engine = discus_rs::RtaEngine::new(None);
    engine.rules.iter().map(|r| r.name.clone()).collect()
}

/// Python module entry point
#[pymodule]
fn _native(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(check, m)?)?;
    m.add_function(wrap_pyfunction!(kill, m)?)?;
    m.add_function(wrap_pyfunction!(is_alive, m)?)?;
    m.add_function(wrap_pyfunction!(get_rules, m)?)?;
    m.add("__version__", "0.1.0")?;
    Ok(())
}
