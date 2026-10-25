# Implemented language — NOVA-X 0.5

This document specifies implemented behavior, not planned features.

## Source and program structure

A UTF-8 `.nx` file contains function definitions. Function names must be unique.
A program must define `fn main() -> int` without parameters. Exit status follows
the host platform's convention for a C `int main` return value.

```text
fn function_name(argument: int, text: str) -> int {
    return argument;
}
```

Parameters are immutable. Calls may precede the function's definition and may
be recursive. No overloads, default parameters, void returns, external function
declarations, or imports exist. A function call can be a standalone statement;
its return value is then discarded. All reachable function exits must return a
value. The return analysis is conservative: even `while true` requires a return
after the loop. Statements after an unconditional transfer are rejected.

## Types and bindings

- `int`: signed i32, from -2147483648 through 2147483647.
- `str`: a reference to immutable, NUL-terminated UTF-8 static storage.
- `let name = expression;` creates an immutable binding.
- `var name: int = expression;` creates a mutable binding with a checked annotation.
- An omitted annotation is inferred. A binding's type cannot change.
- Blocks create lexical scopes; shadowing in a nested scope is allowed.
- `true` is integer 1; `false` is integer 0. Conditions accept only integers;
  zero is false and any nonzero integer is true.

String literals use double quotes and JSON escape syntax. Embedded NUL and
invalid Unicode surrogates are rejected. Literal storage remains valid for the
program's lifetime, including after returning from a function.

## Expressions

Precedence, from low to high:

| Operators | Meaning |
| --- | --- |
| `\|\|` | Short-circuit logical OR |
| `&&` | Short-circuit logical AND |
| `== !=` | Equality |
| `< > <= >=` | Ordering |
| `+ -` | Integer addition/subtraction |
| `* / %` | Integer multiplication/division/remainder |
| Unary `- !` | Checked negation / logical NOT |

Binary operators at the same precedence associate left-to-right. Operands and
function arguments are evaluated left-to-right. Logical operators skip their
right operand when possible and return integer 0 or 1. Static type checking
still checks skipped operands.

Arithmetic accepts integers only. Overflow causes a runtime error; there is no
implicit wrapping. Division truncates toward zero. Remainder has the dividend's
sign. Zero divisors and the pair `-2147483648`, `-1` for either `/` or `%` cause
runtime errors, including inside optimized builds.

Comparisons accept two operands of the same type. Integer comparisons are
signed; string comparisons compare UTF-8 byte sequences by content (not pointer
identity), without locale or normalization. They return integer 0 or 1.

## Statements and built-ins

```text
name = expression;
name += expression;  // Also -= *= /= %=; integers only.
print(expression);
if condition { ... } else if condition { ... } else { ... }
while condition { ... }
break;
continue;
return expression;
```

`break` and `continue` target the innermost `while`. Both are invalid outside
loops. A simple expression statement must be a function call.

`print(int)` uses decimal output; `print(str)` writes text as data. Both append
a newline. `len(str) -> int` counts UTF-8 bytes, not Unicode characters.
`print`, `printf`, and `len` cannot be declared as user functions. Runtime
errors write `nova runtime error: ...` to stderr and terminate with code 1.

Line comments start with `//`. Block comments use `/* ... */` and cannot nest.
`@optimize(speed)` may prefix a function but makes no performance guarantee.

## Host ABI and runtime

Integers lower to LLVM i32; strings lower to pointers to static UTF-8 bytes.
User function symbols are prefixed with `nx_user_`, except `main`. This is an
internal ABI, not a stable FFI. The C runtime supplies text comparison, byte
length, and runtime failure reporting. Local stack slots are allocated once at
function entry. Recursion depth and stack capacity remain host-dependent.

## Compiler diagnostics and resource limits

Syntax and semantic errors identify the source file, one-based line and column,
source excerpt, and a caret marker. Columns count Unicode code points. CRLF
input is normalized by the CLI when reading text. The compiler validates names,
types, call arities, mutability, returns, and control transfers before optimization
or LLVM generation, including code on statically skipped logical RHS branches.

The front end limits sources to 1 MiB of UTF-8, 100,000 non-comment tokens, and
128 tracked parser nesting levels. Python recursion limits can also reject very
deep expression trees; those failures are converted to diagnostics. These bounds
are implementation limits, not a security sandbox or a complete fuzzing audit.
