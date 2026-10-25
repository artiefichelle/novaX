# NOVA-X 0.4 — experimental systems-language compiler

NOVA-X compiles a small typed language to LLVM IR and native executables via
Clang. The goal is a systems language; version 0.4 is a tested foundation,
not a complete replacement for C++ or Rust. See `ROADMAP.md` for unfinished work
and `LANGUAGE.md` for the implemented language rules.

## Quick start

Clone this repository, or extract `nova-x-compiler-v0.4.zip` and enter `nova-x`.
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

`src/runtime.c` must stay beside `src/novax.py`. Native builds compile both the
LLVM module and this runtime. `--emit-llvm -o program.ll` writes verified IR;
link that IR with `src/runtime.c` to build an executable manually.

## Example

```text
fn select(flag: int, name: str) -> str {
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

## New in 0.4

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

`int` and `str`, inferred or explicit variable types, immutable `let`, mutable
`var`, typed functions and returns, recursion, `print`, lexical scopes,
`if` / `else if` / `else`, `while`, `break`, `continue`, short-circuit logic,
UTF-8 text and JSON-style escapes, line and non-nested block comments.
`true` and `false` are integer values 1 and 0. No separate Boolean type exists.

## Validation and limits

Tests cover arithmetic boundaries and runtime failures at `-O0` and `-O3`,
short-circuit behavior, type errors, text, nested loops, symbol isolation,
stack-slot placement, and CLI file preservation. Run the suite locally.

Strings refer to immutable static data; no heap allocation or ownership model
exists yet. Arrays, structs, pointers, references, modules, file I/O, a package
manager, debugger integration, and a formal memory-safety model remain future
work. Text concatenation and input are not implemented. This compiler is
experimental and should only compile trusted programs.

`@optimize(speed)` and `--opt-report` expose deterministic optimization only.
The compiler makes no AI/network calls and claims no speed advantage over
C++ or Rust. `AI_PLUGIN_SPEC.md` is a proposed extension, not a working feature.
