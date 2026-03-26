/**
 * test_discus.c — Unit tests for C bindings
 *
 * Build: make test
 */

#include "discus.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

static int tests_passed = 0;
static int tests_failed = 0;

#define TEST(name) static void name(void)
#define RUN(name) do { \
    printf("  %-40s", #name); \
    name(); \
    printf("✓\n"); \
    tests_passed++; \
} while(0)

#define ASSERT(cond) do { \
    if (!(cond)) { \
        printf("✗ FAIL: %s (line %d)\n", #cond, __LINE__); \
        tests_failed++; \
        return; \
    } \
} while(0)

TEST(test_init) {
    int rc = discus_init(NULL);
    ASSERT(rc == DISCUS_OK);
}

TEST(test_check_returns_result) {
    DiscusCheckResult result;
    int rc = discus_check("test-session", "Hello, world!", &result);
    ASSERT(rc == DISCUS_OK);
    ASSERT(result.allowed == true);
    ASSERT(strcmp(result.session_id, "test-session") == 0);
    ASSERT(strcmp(result.decision, "Pass") == 0);
    ASSERT(result.results_json != NULL);
    ASSERT(strlen(result.results_json) > 0);
    discus_free_result(&result);
}

TEST(test_kill_and_is_alive) {
    const char* sid = "kill-test-c";
    ASSERT(discus_is_alive(sid) == true);
    int rc = discus_kill(sid);
    ASSERT(rc == DISCUS_OK);
    ASSERT(discus_is_alive(sid) == false);
}

TEST(test_check_after_kill) {
    const char* sid = "check-kill-c";
    discus_check(sid, "test", &(DiscusCheckResult){0});
    discus_kill(sid);

    DiscusCheckResult result;
    discus_check(sid, "test", &result);
    ASSERT(result.allowed == false);
    ASSERT(strcmp(result.decision, "Kill") == 0);
    discus_free_result(&result);
}

TEST(test_get_rules) {
    char* rules_json = NULL;
    int rc = discus_get_rules(&rules_json);
    ASSERT(rc == DISCUS_OK);
    ASSERT(rules_json != NULL);
    ASSERT(strstr(rules_json, "SATYA") != NULL);
    ASSERT(strstr(rules_json, "DHARMA") != NULL);
    discus_free_string(rules_json);
}

TEST(test_null_safety) {
    ASSERT(discus_check(NULL, "test", NULL) != DISCUS_OK);
    ASSERT(discus_kill(NULL) != DISCUS_OK);
    ASSERT(discus_is_alive(NULL) == false);
}

TEST(test_shutdown) {
    discus_shutdown();
    /* After shutdown, init should work again */
    ASSERT(discus_init(NULL) == DISCUS_OK);
}

int main(void) {
    printf("\n=== libdiscus C Binding Tests ===\n\n");

    discus_init(NULL);

    RUN(test_init);
    RUN(test_check_returns_result);
    RUN(test_kill_and_is_alive);
    RUN(test_check_after_kill);
    RUN(test_get_rules);
    RUN(test_null_safety);
    RUN(test_shutdown);

    printf("\n=== Results: %d passed, %d failed ===\n\n", tests_passed, tests_failed);

    discus_shutdown();
    return tests_failed > 0 ? 1 : 0;
}
