# Toward a NOVA-X systems language

The user's intended direction is a systems language similar in purpose to C++
or Rust. A version number does not establish completeness. Version 0.15 is a
foundation with three primitive types, integer arrays and nested structs, static text, native code generation, and checked
integer operations. The following capabilities are not implemented.

## Before a 1.0 scope can be frozen

1. Define supported targets, ABI, compatibility policy, and intended memory model.
2. Extend the type system with integer-width, floating-point, and character types;
   conversions, literals, overflow policy, and layout rules.
3. Extend the by-value aggregate model with array-valued fields, enums, slices,
   additional element types, and a separately specified reference model.
4. Extend the selected unique ownership model beyond BoxInt to general owned types,
   checked references, lifetimes and FFI. Do not claim Rust-like safety
   without enforcement and adversarial validation.
5. Extend file modules with package/dependency policy, separate compilation,
   reproducible builds, and an explicit field-visibility design.
6. Define error handling and the standard library: text, I/O, files, collections,
   command-line arguments, and process/environment access.

## Completed in 0.11

- [x] Relative file imports, explicit aliases, public/private names and qualified calls/types.
- [x] Canonical deduplication, transitive modules, cycle detection and import resource limits.
- [x] Imported-source diagnostics and protection against overwriting source dependencies.
- [x] Multi-file example and module-specific tests.
- [x] Record the user's choice of automatic reclamation with checked ownership rules;
  define its initial design work in `OWNERSHIP_DESIGN.md` without claiming implementation.

## Completed in 0.10

- [x] Nested struct fields, chained reads/writes, independent copies through calls
  and returns, and forward type references.
- [x] Cycle detection and conservative layout-size/nesting resource limits.
- [x] Native tests and an executable nested-struct example.

## Completed in 0.9

- [x] Flat named structs with primitive fields, full named initialization,
  field reads and mutable local field writes.
- [x] Struct/array parameters and returns with by-value copies and immutable
  parameters, preserving array bounds checks and avoiding escaping stack references.
- [x] Aggregate type/mutability checks, evaluation-order tests, native calls at
  `-O0` and `-O3`, and a combined runnable example.

## Completed in 0.8

- [x] Conservative interval facts and a semantics-preserving modulo reduction
  for nonnegative bounded operands, including simple-loop invariants.
- [x] Differential checks against the disabled pass and seeded reference programs,
  plus signed-boundary interval tests and preservation of runtime errors.
- [x] Reproducible interleaved benchmark vs 0.7 and C, including a manually tuned
  C comparison and raw samples. Broader benchmarks remain unfinished.

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

## Completed in 0.12

`BoxInt`, `box`, `read_box` and `write_box` now implement restricted unique heap ownership, moves and automatic drops. General references, owned aggregate fields and lifetime checking remain unfinished. `OWNERSHIP_DESIGN.md` defines the implemented subset and its conservative control-flow restrictions.

## Completed in 0.13

- [x] Merge ownership only along branches reaching a continuation.
- [x] Check loop-header availability on normal and continue backedges.
- [x] Track break exits separately from returned paths and nested loop transfers.
- [x] Validate loop ownership with native O0/O3 tests, allocation counters and ASan.

General references, owned aggregates and a full lifetime/alias analysis remain
future work. The implemented structured analysis is not a general borrow checker.

## Completed in 0.14

- [x] Decimal integer console input with explicit i32 range checks.
- [x] EOF-aware input into a mutable BoxInt without ownership transfer.
- [x] Defined token/whitespace rules and diagnostics for invalid input.
- [x] Native stdin tests at O0/O3, imported-module calls and sanitizer boundary tests.

Text input, files, owned strings and recoverable errors remain open.

## Completed in 0.15

- [x] Owned immutable UTF-8 Text with explicit clone and concatenation.
- [x] Borrowing byte length, checked indexing, content equality and printing.
- [x] Generalize move/drop and loop availability rules across BoxInt and Text.
- [x] Keep static strings separate from owned pointers during code generation.
- [x] Validate normal-exit reclamation with allocation counters, ASan and UBSan.

Next foundations remain owned aggregates, general checked references/lifetimes,
file/text input, collections, more numeric types and a declared platform matrix.
