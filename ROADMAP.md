# Toward a NOVA-X systems language

The user's intended direction is a systems language similar in purpose to C++
or Rust. A version number does not establish completeness. Version 0.7 is a
foundation with three primitive types, local integer arrays, static text, native code generation, and checked
integer operations. The following capabilities are not implemented.

## Before a 1.0 scope can be frozen

1. Define supported targets, ABI, compatibility policy, and intended memory model.
2. Extend the type system with integer-width, floating-point, and character types;
   conversions, literals, overflow policy, and layout rules.
3. Extend local integer arrays to a specified aggregate model: structs, enums,
   slices, additional element types, and safe parameter/return rules.
4. Choose an explicit ownership/lifetime model before adding mutable references,
   pointers, allocation, deallocation, and FFI. Do not claim Rust-like safety
   without enforcement and adversarial validation.
5. Define modules, visibility, imports, dependencies, and reproducible builds.
6. Define error handling and the standard library: text, I/O, files, collections,
   command-line arguments, and process/environment access.

## Completed in 0.7

- [x] Local fixed-size `int[N]` arrays, inferred/annotated sizes, initialization,
  by-value copies, same-size reassignment, and mutable element writes.
- [x] Checked read/write indexing at all optimization levels and `len(array)`.
- [x] Define local storage/lifetime restrictions before exposing array references.
- [x] Native and frontend tests for bounds, copying, evaluation order, empty arrays,
  type/mutability errors, and size limits; publish a runnable array example.

## Completed in 0.6

- [x] Introduce a distinct `bool` type with typed variables, functions, comparisons,
  and explicit integer/Boolean conversions.
- [x] Require Boolean conditions and logical operands; reject accidental arithmetic
  or implicit conversions involving truth values.
- [x] Publish migration rules, update examples, and add frontend/backend tests.

## Completed in 0.5

- [x] Replace tuple ASTs with source-spanned dataclass nodes and inferred expression types.
- [x] Separate name/type/control-flow analysis from LLVM lowering.
- [x] File/line/column diagnostics with source excerpts.
- [x] Independent lexer/parser/analyzer tests, including import without LLVM installed.
- [x] Initial input limits, seeded malformed-input smoke tests, and integer-expression
  differential tests. Full fuzzing and a reference interpreter remain unfinished.
- [x] Record the current tested target, unstable ABI, and pre-1.0 compatibility policy
  in `ARCHITECTURE.md`. This does not promise additional targets or memory safety.

## Remaining compiler and tooling work

- Add property and fuzz testing, malformed-input limits, and differential tests
  against an interpreter with the same arithmetic rules.
- Validate Linux and additional architectures; publish an explicit target matrix.
- Add CI, release/version policy, packaging, formatter, language-server support,
  debug metadata, debugger integration, and measurable benchmarks.
- Audit native symbol boundaries, runtime behavior, and memory/stack limits.

## Acceptance criteria for 1.0

Freeze a written feature specification first. Implement and test every promised
feature on every declared supported target, publish known limitations, and verify
clean installation, reproducible builds, documentation examples, error behavior,
and version migration. Do not label the language complete before that work is done.
