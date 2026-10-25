# NOVA-X Compiler Prototype 0.2

An **experimental** C++/Rust-inspired programming-language compiler, producing native executables through LLVM IR and Clang. This is **not a production-safe compiler**, and the language does **not yet** implement Rust-style ownership, borrowing, memory-safe references, strings, classes, GPU execution, or a real AI optimizer. No speedup over C++ or Rust is claimed.

## Requirements

- Python 3.10+
- `pip install -r requirements.txt`
- `clang` on PATH (required for native executables)

## Run

```bash
python src/novax.py examples/hello.nx -o hello --opt-report
./hello
python src/novax.py examples/fibonacci.nx -O3 -o fib
./fib
python src/novax.py examples/hello.nx --emit-llvm -o hello.ll
python -m unittest discover -s tests -v
```

## Language subset

- `.nx` files; `fn name(arg: int) -> int { ... }`
- `let` immutable and `var` mutable bindings with lexical block scopes
- signed 32-bit `int` arguments, return values, integer literals
- arithmetic and comparison expressions, `if`/`else`, `while`, recursion, `return`, and `print(int)`
- `@optimize(speed)` accepted as an annotation (not currently a speed guarantee)
- compile-time static checks for undeclared variables, invalid assignments to `let`, duplicate functions, wrong call arities, and missing returns
- deterministic AST constant folding for safe nonnegative i32 intermediate arithmetic
- LLVM IR generation and Clang `-O0` .. `-O3`

## Limitations and security

Only simple integer code is supported. Arithmetic overflow, division by zero, and some control-flow corner cases are *not* yet given fully safe, defined semantics. `&&` and `||` short-circuit and produce 0 or 1. Boolean literals are integer values (`false` = 0, `true` = 1), not a separate type. Block comments cannot be nested. Loop-local stack allocations are not yet hoisted, so very long loops with local declarations may exhaust the stack. `int` is an i32; no implicit heap allocations, borrowing, classes, or AI code execution exist. Compile/run only trusted sources in this prototype.

## AI extension design (not yet executed)

A proposed optimizer protocol is documented in `AI_PLUGIN_SPEC.md`. An AI process should suggest edits, but only a separate verifier/test pipeline may approve them. The current compiler **does not contact an AI model**.

## Performance validation

Benchmark against comparable optimized C++ and Rust programs on the same machine. Verify outputs and record runtime, compiler versions, memory usage, and hardware; the 10,000x target is a research aspiration for special workloads rather than a language-wide promise.

## New in 0.2

- Short-circuit `&&` / `||`: skipped operands do not run function calls.
- `else if` chains.
- `break;` and `continue;` affect the innermost `while` loop; use outside a loop is rejected.
- Function calls as statements, for example `greet();` (the return value is discarded).
- `true` and `false` literals with integer semantics.
- Multi-line `/* ... */` comments, with an error for unterminated comments.
- Full negative i32 literal range, including `-2147483648`.
- The C runtime name `printf` is reserved to prevent conflicting declarations.

Try `python src/novax.py examples/control_flow.nx -o control_flow` and run
`./control_flow`. Expected output: `1`, `3`, `4`, `42` on separate lines.

The project remains an experimental integer-only compiler. Strings, arrays,
separate Boolean types, ownership, and memory safety are not implemented.
