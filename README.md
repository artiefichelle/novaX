# NOVA-X Compiler Prototype 0.3

NOVA-X is an experimental compiler for a small C++/Rust-inspired language.
It translates source to LLVM IR and uses Clang to build native executables.
Version 0.3 adds typed UTF-8 strings. It does not implement Rust ownership,
borrowing, arrays, classes, GPU execution, or an AI optimizer.

## Install and run

Download `nova-x-compiler-v0.3.zip`, extract it, and open the `nova-x` directory.
Requirements: Python 3.10+ and Clang on PATH.

```bash
python -m pip install -r requirements.txt
python src/novax.py examples/strings.nx -o strings
./strings
python src/novax.py examples/fibonacci.nx -O3 -o fib
./fib
python src/novax.py examples/hello.nx --emit-llvm -o hello.ll
python -m unittest discover -s tests -v
```

## Strings and types — new in 0.3

```text
fn choose(flag: int, name: str) -> str {
    if flag { return name; }
    return "NOVA-X";
}

fn main() -> int {
    let greeting: str = "Hallo Welt 🌍";
    var message = choose(true, greeting);
    print(message);
    message = "Text mit\nZeilenumbruch";
    print(message);
    return 0;
}
```

- `int`: signed 32-bit integer; `str`: immutable UTF-8 text.
- `let` and `var` infer their type or accept an explicit `: int` / `: str`.
- `var` allows reassignment of the same type; `let` is immutable.
- Function parameters and return values explicitly declare `int` or `str`.
- `print(value);` prints an integer or string and appends a newline.
- String literals use double quotes and JSON-style escapes, including `\n`,
  `\t`, `\"`, `\\`, and `\uXXXX`. Unicode text and emoji are supported.
- Type mismatches in declarations, assignments, calls, returns, conditions,
  and operators produce compiler errors. `main` must return `int` and take no arguments.
- Strings live in static storage for the program's lifetime. A string variable
  may refer to a different literal, but individual characters cannot be modified.

String concatenation, comparison, indexing, length, interpolation, input, and
embedded NUL characters are not supported. Operators and conditions require
integers; strings are not implicitly converted to numbers or truth values.

## Existing language features

- Functions, recursion, lexical block scopes, and function calls as statements.
- Arithmetic `+ - * / %`, comparisons `== != < <= > >=`, unary `-` and `!`.
- `if` / `else if` / `else`, `while`, `break`, `continue`, and `return`.
- Short-circuit `&&` / `||` with integer results 0 or 1.
- `true` / `false` are integer literals 1 / 0, not a separate Boolean type.
- Line comments `// ...` and non-nested block comments `/* ... */`.
- Full signed i32 literal range, including `-2147483648`.
- Deterministic constant folding, Clang `-O0` through `-O3`, and `--opt-report`.
- `@optimize(speed)` is accepted as an annotation, with no speed guarantee.

## Validation

The suite contains 20 tests including existing integer-language regressions,
string function calls and returns, reassignment, UTF-8 and escape sequences,
format-string payloads printed as data, malformed literals, and type errors.
Native feature tests execute at both `-O0` and `-O3`.

## Prototype limitations

Arithmetic overflow, division by zero, and certain control-flow corner cases
are not yet given fully safe, defined semantics. Loop-local stack allocations
are not hoisted; very long loops with local declarations may exhaust the stack.
Compile and run trusted programs only. This is not a production-safe compiler.

The proposed AI extension protocol is in `AI_PLUGIN_SPEC.md`; the compiler
makes no network calls and runs no AI model. No speed advantage over C++ or
Rust is claimed. Performance claims require equivalent programs, verified
outputs, and recorded hardware, compiler versions, runtime, and memory usage.
