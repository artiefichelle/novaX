# NOVA-X 0.9 — experimental systems-language compiler

NOVA-X compiles a small typed language to LLVM IR and native executables via
Clang. The goal is a systems language; version 0.9 is a tested foundation,
not a complete replacement for C++ or Rust. See `ROADMAP.md` for unfinished work
and `LANGUAGE.md` for the implemented language rules.

## Quick start

Clone this repository, or extract `nova-x-compiler-v0.9.zip` and enter `nova-x`.
Requirements: Python 3.10+, the dependency in `requirements.txt`, and Clang with
a C11-capable system toolchain. Native validation was performed on macOS ARM64;
other targets have not yet been validated.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python src/novax.py --version
python src/novax.py examples/systems.nx --check
python src/novax.py examples/systems.nx -o systems
./systems
python -m unittest discover -s tests -v
```

`src/frontend.py`, `src/backend.py`, `src/ranges.py`, and `src/runtime.c` must stay beside `src/novax.py`. Native builds compile both the
LLVM module and this runtime. `--emit-llvm -o program.ll` writes verified IR;
link that IR with `src/runtime.c` to build an executable manually.

## Example

```text
fn select(flag: bool, name: str) -> str {
    if flag { return name; }
    return "NOVA-X";
}

fn main() -> int {
    var count = 0;
    while count < 3 {
        count += 1;
        print(count);
    }
    let message: str = select(true, "Hallo Welt 🌍");
    print(message);
    print(len(message));
    print(message != "");
    return 0;
}
```

## New in 0.9 — structs and aggregate function values

```text
struct Point { x: int, y: int }

fn shifted(point: Point) -> Point {
    var copy = point;
    copy.x = copy.x + 5;
    return copy;
}

fn sum(values: int[3]) -> int {
    return values[0] + values[1] + values[2];
}
```

- Named structs with `int`, `bool`, and `str` fields; construct values with
  `new Point {x: 1, y: 2}` and read fields with `point.x`.
- All fields must be initialized exactly once. Initializers evaluate in their
  written order; types and field names are checked before code generation.
- Structs and fixed-size integer arrays may be parameters and return values.
  Arrays of different sizes and differently named structs are distinct types.
- Parameters and `let` bindings remain immutable. Copy to `var` to modify a field
  or array element. Argument passing, returning, assignment, and initialization
  use value copies, without mutable aliasing or heap allocation.
- Struct field writes use plain assignment; nested/array-valued fields, methods,
  inheritance, aggregate comparison, and whole-aggregate printing are not implemented.
- 89 tests include native aggregate calls/returns at `-O0` and `-O3`, copies,
  mutability, initializer order, invalid definitions, and return-value bounds.
- `examples/aggregates.nx` prints `1`, `6`, `9`, `true`, `60` on separate lines.

## Added in 0.8 — interval-proven remainder optimization

NOVA-X 0.8 is **3.57x faster than 0.7 on the unchanged checksum benchmark**:
57.38 ms becomes 16.06 ms for 20 million iterations on the tested Apple M4.
This is a workload-specific result; no general C/Rust performance advantage is claimed.
See `BENCHMARKS.md` and the reproducible `benchmark-nova-x-v0.8.zip` bundle.

- Conservative interval analysis tracks successful checked integer results,
  local array element ranges, and invariants in straight-line while bodies.
- For a positive constant `m` and proven `0 <= x < 2*m`, `x % m` becomes a
  comparison/select/subtraction. Operands and their side effects still evaluate.
- Intermediate arithmetic overflow and array bounds checks remain active.
- Unknown or unsupported cases keep the previous code generation. There is no
  new source syntax and no relaxed arithmetic or memory policy.
- Enabled at `-O2` / `-O3`; use `--no-range-opt` to disable it. `--opt-report`
  reports the number of `modulo_reductions`.
- 78 tests include signed arithmetic boundary facts, loop mutation/shadowing,
  complex-loop fallbacks, errors and side effects, plus seeded modular programs
  checked against a reference with the pass enabled and disabled.

## Added in 0.7 — local fixed-size integer arrays

```text
var values: int[3] = [10, 20, 30];
let original = values;
values[1] = 25;
print(values[1]);
print(original[1]); // Still 20: arrays are copied by value.
print(len(values));
```

- `int[N]` is a fixed-size local array, with inferred sizes for array literals.
- All elements must be integers; sizes range from 0 through 4096.
- Index reads and writes check both bounds, including negative indices.
- `var` permits element writes and same-size whole-array assignment; `let` does not.
- `len(array)` returns its element count; `len(str)` still counts UTF-8 bytes.
- Arrays have value semantics and local stack storage. They cannot be parameters
  or return values and do not expose pointers or references.
- Only named local arrays may be indexed. No nested arrays, slices, resizing,
  Boolean/string arrays, array comparisons, array printing, or element compound
  assignments are implemented. Use `a[i] = value` for element writes.
- The suite now has 67 tests, including bounds failures and array behavior at
  `-O0` and `-O3`. Try `examples/arrays.nx` (outputs 105, 20, 25, 4).

## Added in 0.6 — distinct Boolean values

- `bool` is a distinct type for bindings, parameters, and return values.
- `true` / `false`, comparisons, `!`, `&&`, and `||` produce Boolean values.
- `if`, `while`, `!`, `&&`, and `||` require Boolean operands.
- `print(bool)` writes `true` or `false`. Boolean values support `==` / `!=`;
  arithmetic and ordering on Boolean values are rejected.
- Explicit `to_bool(int)` maps zero to false and nonzero to true.
  `to_int(bool)` maps false to 0 and true to 1.
- The complete suite now has 56 tests, including positive and negative type
  tests and native Boolean calls and short-circuit behavior at `-O0` / `-O3`.

### Migration from 0.5

This is an intentional source-compatibility change in an experimental release.
Replace `if number` / `while number` with `if number != 0` / `while number != 0`
or use `to_bool(number)`. Change predicate parameters and return types to `bool`.
Use `to_int(comparison)` where a numeric result is required. Output of Boolean
expressions changes from `0` / `1` to `false` / `true`.
All shipped examples have been migrated; older release ZIPs remain unchanged.
See `examples/booleans.nx` for a complete example.

## Added in 0.5

- A source-spanned, typed dataclass AST replaces the tuple-based AST.
- Lexer, parser, name resolution, type checking, and control-flow validation live
  in `src/frontend.py`, which has no LLVM or Clang dependency.
- `src/backend.py` lowers analyzed nodes to LLVM; `src/novax.py` runs the CLI.
- Source errors report filename, line, column, source excerpt, and caret.
- Semantic validation runs before optimization, including skipped logical operands.
- Input limits: 1 MiB source, 100,000 tokens, and controlled nesting failures.
  Huge integer literals produce diagnostics rather than Python conversion errors.
- 49 tests, including 400 seeded malformed-input cases and 40 generated integer
  expressions compared with a Python reference at `-O0` and `-O3`.

Run only the LLVM-independent front-end suite with system Python:

```bash
python3 -m unittest discover -s tests -p test_frontend.py -v
```

See `ARCHITECTURE.md` for compiler stages and the current target/ABI policy.

## Added in 0.4

- Checked signed i32 addition, subtraction, multiplication, and unary negation.
  Overflow ends the program with exit code 1 and a message on stderr.
- Checked division and remainder: zero divisors and `INT_MIN / -1` (including
  the corresponding remainder) produce a runtime error.
- String content comparisons `== != < <= > >=` and `len(str)` in UTF-8 bytes.
- Compound assignments `+= -= *= /= %=` for mutable integers.
- Local stack slots allocated once per function invocation, outside loops.
- User function symbols isolated from C runtime symbols.
- `--version`, `--check`, and LLVM verification before writing output.
- Temporary build files no longer overwrite unrelated `.ll` files. A failed
  backend compilation preserves existing output; output cannot equal source.

## Existing features

`int`, `bool`, and `str`, inferred or explicit variable types, immutable `let`, mutable
`var`, typed functions and returns, recursion, `print`, lexical scopes,
`if` / `else if` / `else`, `while`, `break`, `continue`, short-circuit logic,
UTF-8 text and JSON-style escapes, line and non-nested block comments.
`true` and `false` have type `bool`; conversions to and from `int` are explicit.

## Validation and limits

Tests cover arithmetic boundaries and runtime failures at `-O0` and `-O3`,
short-circuit behavior, type errors, text, nested loops, symbol isolation,
stack-slot placement, and CLI file preservation. Run the suite locally.

Strings refer to immutable static data; no heap allocation or ownership model
exists yet. Nested structs, slices, pointers, references, modules, file I/O, a package
manager, debugger integration, and a formal memory-safety model remain future
work. Text concatenation and input are not implemented. This compiler is
experimental and should only compile trusted programs.

`@optimize(speed)` and `--opt-report` expose deterministic optimization only.
The compiler makes no AI/network calls and claims no speed advantage over
C++ or Rust. `AI_PLUGIN_SPEC.md` is a proposed extension, not a working feature.
