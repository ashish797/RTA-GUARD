/**
 * discus.h — C bindings for RTA-GUARD Discus
 *
 * Header file for the deterministic AI session kill-switch.
 * Links against discus_rs.wasm via wasmtime C API.
 */

#ifndef DISCUS_H
#define DISCUS_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Result codes */
#define DISCUS_OK              0
#define DISCUS_ERR            -1
#define DISCUS_ERR_INIT       -2
#define DISCUS_ERR_SESSION    -3
#define DISCUS_ERR_WASM       -4

/** Check result structure */
typedef struct {
    bool     allowed;
    char*    session_id;   /* caller must free */
    char*    decision;     /* "Pass", "Warn", "Kill" — caller must free */
    char*    results_json; /* full results as JSON — caller must free */
} DiscusCheckResult;

/**
 * Initialize the Discus engine.
 * @param wasm_path  Path to discus_rs.wasm binary
 * @return DISCUS_OK on success
 */
int discus_init(const char* wasm_path);

/**
 * Check input through the RTA rules engine.
 * @param session_id  Session identifier
 * @param input       Text to evaluate
 * @param out         Output result (caller frees fields)
 * @return DISCUS_OK on success
 */
int discus_check(const char* session_id, const char* input, DiscusCheckResult* out);

/**
 * Kill a session.
 * @param session_id  Session to kill
 * @return DISCUS_OK on success
 */
int discus_kill(const char* session_id);

/**
 * Check if a session is alive.
 * @param session_id  Session to check
 * @return true if alive, false if killed or error
 */
bool discus_is_alive(const char* session_id);

/**
 * Get list of active rule names as JSON array.
 * @param out_rules  Output JSON string (caller must free)
 * @return DISCUS_OK on success
 */
int discus_get_rules(char** out_rules);

/**
 * Free a string allocated by discus_* functions.
 * @param str  String to free
 */
void discus_free_string(char* str);

/**
 * Free all fields in a DiscusCheckResult.
 * @param result  Result to free
 */
void discus_free_result(DiscusCheckResult* result);

/**
 * Shutdown the Discus engine and free resources.
 */
void discus_shutdown(void);

#ifdef __cplusplus
}
#endif

#endif /* DISCUS_H */
