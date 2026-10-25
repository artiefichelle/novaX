/* NOVA-X 0.4 runtime. No allocation or string ownership is required yet. */
#include <stdint.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Noreturn void nx_rt_fail(const char *message) {
    fprintf(stderr, "nova runtime error: %s\n", message);
    exit(1);
}

/* len counts UTF-8 bytes, not Unicode code points. */
int32_t nx_rt_len(const char *text) {
    size_t length = strlen(text);
    if (length > INT32_MAX) nx_rt_fail("string length exceeds i32 range");
    return (int32_t)length;
}

/* Normalize the C comparator to a stable -1, 0, or 1. */
int32_t nx_rt_compare(const char *a, const char *b) {
    int result = strcmp(a, b);
    return (result > 0) - (result < 0);
}

/* A BoxInt has one owner; generated code moves and drops that owner. */
int32_t *nx_rt_box_new(int32_t value) {
    int32_t *p = malloc(sizeof(*p));
    if (!p) nx_rt_fail("out of memory");
    *p = value;
    return p;
}
int32_t nx_rt_box_get(int32_t *p) {
    if (!p) nx_rt_fail("invalid BoxInt owner");
    return *p;
}
int32_t nx_rt_box_set(int32_t *p, int32_t value) {
    if (!p) nx_rt_fail("invalid BoxInt owner");
    *p = value;
    return value;
}
void nx_rt_box_drop(int32_t *p) { free(p); }
