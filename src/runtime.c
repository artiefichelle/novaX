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
