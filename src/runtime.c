/* NOVA-X runtime: checked operations, unique owners and console input. */
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

/* Locale-independent decimal tokens, separated by ASCII whitespace. */
static int nx_rt_space(int ch) {
    return ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' || ch == '\v' || ch == '\f';
}
static int nx_rt_parse_int(int32_t *output) {
    if (fflush(stdout) == EOF) nx_rt_fail("output error before input");
    int ch;
    do { ch = getchar(); } while (nx_rt_space(ch));
    if (ch == EOF) {
        if (ferror(stdin)) nx_rt_fail("input read error");
        return 0;
    }
    int negative = ch == '-';
    if (ch == '+' || ch == '-') ch = getchar();
    uint32_t value = 0;
    uint32_t limit = negative ? UINT32_C(2147483648) : UINT32_C(2147483647);
    int digits = 0;
    while (ch != EOF && !nx_rt_space(ch)) {
        if (ch < '0' || ch > '9') nx_rt_fail("invalid integer input");
        uint32_t digit = (uint32_t)(ch - '0');
        if (value > (limit - digit) / 10) nx_rt_fail("integer input exceeds i32 range");
        value = value * 10 + digit;
        digits = 1;
        ch = getchar();
    }
    if (ferror(stdin)) nx_rt_fail("input read error");
    if (!digits) nx_rt_fail("invalid integer input");
    *output = negative ? (value == UINT32_C(2147483648) ? INT32_MIN : -(int32_t)value) : (int32_t)value;
    return 1;
}
int32_t nx_rt_read_int(void) {
    int32_t value;
    if (!nx_rt_parse_int(&value)) nx_rt_fail("end of input while reading integer");
    return value;
}
int32_t nx_rt_try_read_int(int32_t *owner) {
    if (!owner) nx_rt_fail("invalid BoxInt owner");
    return nx_rt_parse_int(owner);
}
