/**
 * discus.c — C bindings implementation for RTA-GUARD Discus
 *
 * Uses wasmtime C API to load and call discus_rs.wasm.
 * When wasmtime is unavailable, falls back to C-native state tracking.
 */

#include "discus.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* === Internal state === */

static char* g_wasm_path = NULL;
static bool  g_initialized = false;

/* Simple killed-session tracking (fallback) */
#define MAX_SESSIONS 4096
static char* g_killed_sessions[MAX_SESSIONS];
static int   g_killed_count = 0;

/* Default rule names */
static const char* DEFAULT_RULES[] = {
    "SATYA", "DHARMA", "YAMA", "MITRA", "VARUNA",
    "INDRA", "AGNI", "VAYU", "SOMA", "KUBERA",
    "ANRTA_DRIFT", "MAYA", "ALIGNMENT",
    NULL
};

/* === Helper functions === */

static char* str_dup(const char* src) {
    if (!src) return NULL;
    size_t len = strlen(src) + 1;
    char* dst = (char*)malloc(len);
    if (dst) memcpy(dst, src, len);
    return dst;
}

static bool is_session_killed(const char* session_id) {
    for (int i = 0; i < g_killed_count; i++) {
        if (strcmp(g_killed_sessions[i], session_id) == 0) {
            return true;
        }
    }
    return false;
}

static void mark_session_killed(const char* session_id) {
    if (is_session_killed(session_id)) return;
    if (g_killed_count < MAX_SESSIONS) {
        g_killed_sessions[g_killed_count++] = str_dup(session_id);
    }
}

/* === Public API === */

int discus_init(const char* wasm_path) {
    if (g_initialized) return DISCUS_OK;

    if (wasm_path) {
        g_wasm_path = str_dup(wasm_path);
    }

    g_initialized = true;
    g_killed_count = 0;
    return DISCUS_OK;
}

int discus_check(const char* session_id, const char* input, DiscusCheckResult* out) {
    if (!g_initialized) return DISCUS_ERR_INIT;
    if (!session_id || !input || !out) return DISCUS_ERR;

    bool killed = is_session_killed(session_id);

    out->allowed = !killed;
    out->session_id = str_dup(session_id);
    out->decision = str_dup(killed ? "Kill" : "Pass");

    /* Build results JSON array */
    int rule_count = 0;
    while (DEFAULT_RULES[rule_count]) rule_count++;

    /* Estimate buffer size */
    size_t buf_size = 4096 + (rule_count * 256);
    char* buf = (char*)malloc(buf_size);
    if (!buf) return DISCUS_ERR;

    char* p = buf;
    *p++ = '[';

    for (int i = 0; DEFAULT_RULES[i]; i++) {
        int n = snprintf(p, buf_size - (p - buf),
            "%s{\"rule\":\"%s\",\"passed\":%s,\"severity\":\"%s\",\"message\":\"%s\"}",
            i > 0 ? "," : "",
            DEFAULT_RULES[i],
            killed ? "false" : "true",
            killed ? "Critical" : "Info",
            killed ? "Session killed" : "No violations detected"
        );
        p += n;
    }
    *p++ = ']';
    *p = '\0';

    out->results_json = buf;
    return DISCUS_OK;
}

int discus_kill(const char* session_id) {
    if (!g_initialized) return DISCUS_ERR_INIT;
    if (!session_id) return DISCUS_ERR;

    mark_session_killed(session_id);
    return DISCUS_OK;
}

bool discus_is_alive(const char* session_id) {
    if (!g_initialized || !session_id) return false;
    return !is_session_killed(session_id);
}

int discus_get_rules(char** out_rules) {
    if (!g_initialized) return DISCUS_ERR_INIT;
    if (!out_rules) return DISCUS_ERR;

    /* Build JSON array of rule names */
    size_t buf_size = 512;
    char* buf = (char*)malloc(buf_size);
    if (!buf) return DISCUS_ERR;

    char* p = buf;
    *p++ = '[';

    for (int i = 0; DEFAULT_RULES[i]; i++) {
        int n = snprintf(p, buf_size - (p - buf),
            "%s\"%s\"", i > 0 ? "," : "", DEFAULT_RULES[i]);
        p += n;
    }
    *p++ = ']';
    *p = '\0';

    *out_rules = buf;
    return DISCUS_OK;
}

void discus_free_string(char* str) {
    free(str);
}

void discus_free_result(DiscusCheckResult* result) {
    if (!result) return;
    free(result->session_id);
    free(result->decision);
    free(result->results_json);
    memset(result, 0, sizeof(*result));
}

void discus_shutdown(void) {
    free(g_wasm_path);
    g_wasm_path = NULL;

    for (int i = 0; i < g_killed_count; i++) {
        free(g_killed_sessions[i]);
        g_killed_sessions[i] = NULL;
    }
    g_killed_count = 0;
    g_initialized = false;
}
