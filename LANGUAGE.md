# Implemented language — NOVA-X 0.11

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
declarations exist. File imports are described below. A function call can be a standalone statement;
its return value is then discarded. All reachable function exits must return a
value. The return analysis is conservative: even `while true` requires a return
after the loop. Statements after an unconditional transfer are rejected.

## Types and bindings

- `int`: signed i32, from -2147483648 through 2147483647.
- `bool`: a distinct truth value, `true` or `false`.
- `int[N]`: a fixed-size array value of N integers; N is 0 through 4096.
- `str`: a reference to immutable, NUL-terminated UTF-8 static storage.
- `let name = expression;` creates an immutable binding.
- `var name: int = expression;` creates a mutable binding with a checked annotation.
- An omitted annotation is inferred. A binding's type cannot change, including an array's size.
- Blocks create lexical scopes; shadowing in a nested scope is allowed.
- Conditions accept only `bool`. There are no implicit conversions between
  `int`, `bool`, and `str`. `to_bool(int)` explicitly tests nonzero;
  `to_int(bool)` explicitly returns 0 or 1.

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
function arguments are evaluated left-to-right. Logical operators require Boolean operands, skip their
right operand when possible, and return `bool`. Static type checking
still checks skipped operands.

Arithmetic accepts integers only. Overflow causes a runtime error; there is no
implicit wrapping. Division truncates toward zero. Remainder has the dividend's
sign. Zero divisors and the pair `-2147483648`, `-1` for either `/` or `%` cause
runtime errors, including inside optimized builds.

Primitive comparisons accept two operands of the same type and return `bool`.
Arrays and structs cannot be compared directly. Integer
comparisons are signed; string comparisons compare UTF-8 byte sequences by
content (not pointer identity), without locale or normalization. Boolean values
support equality and inequality only; their ordering is not defined. Unary `!`
requires and returns `bool`; unary negation requires and returns `int`.

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

`print(int)` uses decimal output; `print(str)` writes text as data. `print(bool)` writes `true` or `false`. All append
a newline. `len(str) -> int` counts UTF-8 bytes, not Unicode characters.
`len(array) -> int` returns the number of elements. Array-literal arguments
to `len` are evaluated left-to-right, including element side effects.
`to_bool(int) -> bool` and `to_int(bool) -> int` are explicit conversions.
`print`, `printf`, `len`, `to_bool`, and `to_int` cannot be declared as user functions. Runtime
errors write `nova runtime error: ...` to stderr and terminate with code 1.

Line comments start with `//`. Block comments use `/* ... */` and cannot nest.
`@optimize(speed)` may prefix a function but makes no performance guarantee.

## Host ABI and runtime

Integers lower to LLVM i32, Boolean values to LLVM i1; strings lower to pointers to static UTF-8 bytes.
User function symbols are prefixed with `nx_user_`, except `main`. This is an
internal ABI, not a stable FFI. The C runtime supplies text comparison, byte
length, and runtime failure reporting. Local stack slots are allocated once at
function entry. Recursion depth and stack capacity remain host-dependent.

## Compiler diagnostics and resource limits

Syntax and semantic errors identify the source file, one-based line and column,
source excerpt, and a caret marker. Columns count Unicode code points. CRLF
input is accepted; diagnostics display source lines without trailing carriage returns. The compiler validates names,
types, call arities, mutability, returns, and control transfers before optimization
or LLVM generation, including code on statically skipped logical RHS branches.

The front end limits sources to 1 MiB of UTF-8, 100,000 non-comment tokens, and
128 tracked parser nesting levels. Python recursion limits can also reject very
deep expression trees; those failures are converted to diagnostics. These bounds
are implementation limits, not a security sandbox or a complete fuzzing audit.

## Local arrays

An array literal `[10, 20, 30]` has type `int[3]`; `[]` has type `int[0]`.
A trailing comma is allowed. Only integer elements are accepted. Array sizes
are compile-time constants and must match any annotation or reassignment target.

Arrays are values: `let b = a;` copies the elements, without aliasing the source.
`var a = [1, 2]; a[0] = 3;` changes a mutable array; `let` prohibits both element
writes and whole-array reassignment. Arrays must be initialized at declaration.
Each local slot is allocated once per function invocation, including inside loops;
a declaration's initializer still runs on each execution of that declaration.

Only named array bindings or parameters can be indexed, with an `int` index. Reads and writes
require `0 <= index < len(array)`. An invalid index terminates with exit code 1
and `nova runtime error: array index out of bounds` on stderr. The check remains
active at every optimization level. Empty arrays have no valid index.

For `a[index] = value`, the index is evaluated once and checked before the RHS
is evaluated. Array literals evaluate elements left-to-right. Array values may
be copied, assigned to same-size locals, passed to matching typed parameters,
and returned from functions. Parameters are immutable value copies; local `var`
copies may be modified. No array references, pointers or closures are exposed. Indexing temporary literals, multidimensional arrays,
non-int arrays, slices, dynamic allocation, resizing, comparison, printing entire
arrays, and element compound assignment are also not implemented.

LLVM storage is `[N x i32]` on the function stack. The per-array size limit does
not cap total stack use: many large locals and recursion can still exhaust the
host stack. Arrays introduce no ownership or borrowing model.

## Interval optimization

Version 0.8 does not change source semantics. At `-O2` and `-O3`, a conservative
range pass may replace remainder by a positive constant with one conditional
subtraction when successful evaluation proves `0 <= dividend < 2*divisor`.
Intermediate operand evaluation, arithmetic failures and array bounds remain
observable. Unsupported range/control-flow patterns fall back to existing code.
`--no-range-opt` disables the pass; `--opt-report` reports its reduction count.

## Structs and aggregate function values (0.9)

```text
struct Point { x: int, y: int }
fn shift(p: Point) -> Point {
    var result = p;
    result.x = result.x + 1;
    return result;
}
```

Structs are declared at file scope and may be used by functions appearing before
the declaration. A struct name identifies a nominal type: different names are
different types even if their fields match. Type and function names occupy
separate namespaces. Fields may have primitive type `int`, `bool`, `str`, or another declared struct
type. Recursive by-value and array-valued struct fields are not supported.

Construct a struct using `new Point {x: 1, y: 2}`. Every field must appear exactly
once, in any order. Expressions evaluate in the order written in the initializer.
Read fields with `p.x`, including a function-return value such as `shift(p).x`.
A plain field assignment `p.x = value;` requires a named mutable `var` root binding;
field compound assignment and writes to temporary results are not implemented.

Functions accept and return struct or fixed-size integer array values. A parameter
is immutable, including its fields/elements. `var copy = parameter;` creates an
independent editable copy. Returning an aggregate copies its value, so no pointer
to a callee's local stack escapes. Array indexing still requires a named binding;
write `let a = make_array(); print(a[0]);` rather than indexing the call directly.

Aggregate storage and calling conventions are internal LLVM/Clang implementation
details. No stable FFI or Rust-style ownership/borrowing guarantee is introduced.
Empty structs and zero-length integer arrays are supported. Many large aggregate
copies or deep recursion can still exhaust the host stack.

## Nested struct layouts (0.10)

Fields can contain other structs by value. Chained reads and writes, such as
`box.start.x`, resolve each field statically. Writes require a mutable root binding;
parameters and `let` roots remain immutable at every depth. Assigning a whole
nested field copies a value of the exact declared nominal type. Function-return
values support chained reads; writes still require a named mutable binding.

All struct names are collected before validating layouts, so forward references
are supported. Direct and indirect cycles are rejected because finite by-value
storage cannot represent them. Maximum nesting depth is 64 edges. A conservative
storage estimate sums 8 bytes for each primitive leaf field, including each copy
of a nested struct; the per-struct limit is 65,536 bytes. Empty structs estimate
zero bytes. This is a compiler resource limit, not a stable ABI size guarantee
or a total stack limit.

## Modules and visibility (0.11)

An entry source file may import another file using `import "file.nx" as alias;`.
The path is relative to the importing file; only relative `.nx` paths are accepted.
Imports are declarations at file scope. Functions and struct definitions can be
prefixed with `pub`; otherwise they are private to their source module.
`alias::function(...)`, `alias::Type`, and `new alias::Type {...}` reference public
names from a direct import. Internal unqualified references resolve within the
current module. There are no glob imports, reexports, external package resolution,
network fetching, module initialization statements, or nested alias paths.

Imported files cannot define `main`. The entry file supplies the one program
entry point. Import cycles and duplicate aliases are errors. Canonical filesystem
paths identify modules; repeated imports use one definition and the same nominal
struct identity. All struct fields are accessible when their type is available;
field-level visibility is not implemented. A public signature or public struct
cannot expose a private struct type in its defining module.

Every module retains its filename and source spans for diagnostics. Before native
output is written, the compiler rejects paths equal to any source dependency.
Imports are ordinary local file reads, not a sandbox. Paths may use `..`; no
project-root confinement is claimed. Limits are 128 files, depth 32 and 4 MiB
combined UTF-8 source, alongside the existing per-file limits.
