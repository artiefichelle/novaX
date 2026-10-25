# NOVA-X 0.13 compiler architecture and policy

## Pipeline

1. `modules.Loader` reads the entry and import graph, validates visibility,
   qualifies declarations/references into module namespaces, and preserves each
   source filename/span. Single-file front-end APIs remain available for unit tests.
2. `frontend.lex(Source)` produces tokens with source spans.
3. `frontend.Parser(tokens).parse()` produces a `Program` containing dataclass
   function, parameter, statement, and expression nodes. Parsing does not require
   LLVM and does not resolve types.
4. `frontend.Analyzer().analyze(program)` resolves function/variable names,
   validates types, mutability, calls and control flow, and annotates every
   expression with `int`, `bool`, `str`, or an aggregate `ArrayType` / `StructType`. Invalid programs stop here.
5. `frontend.optimize_program(program)` folds valid, non-overflowing integer
   arithmetic and retains the original expression span and inferred type.
6. At `-O2` / `-O3`, `ranges.RangeAnalysis` computes conservative intervals.
   Straight-line loops use widening to an invariant and bounded narrowing;
   complex loops use unknown facts. Bottom represents no successful result.
7. `backend.Compiler(program, facts)` lowers nodes, applying proven modulo
   reductions without dropping intermediate arithmetic or array checks.
8. LLVM verifies the module. `--check` stops without writing files; `--emit-llvm`
   writes IR. Native compilation links the IR with `src/runtime.c` through Clang.

`analyze_source(text, filename)` is the convenient front-end-only API. The AST
is mutable: analysis adds types and optimization replaces expression nodes.
Callers must analyze before lowering. AST and Python APIs are internal and are
not covered by a stable compatibility promise.

## Current target policy

- Locally tested: macOS ARM64 with Apple Clang, Python 3.14, llvmlite 0.48.
- The declared Python floor remains 3.10; not every dependency/Python combination
  has been tested. Use a compatible llvmlite wheel from `requirements.txt`.
- Other platforms and cross-compilation are unvalidated. The backend emits the
  current host LLVM triple; no target-selection flag is implemented.
- A C11-capable toolchain and compatible system C runtime are required.
- CI and an independently verified target matrix remain roadmap items.

## ABI and memory policy

`int` is LLVM i32; `bool` is LLVM i1. `str` is a pointer to immutable NUL-terminated UTF-8 static
storage. Calls use the LLVM/Clang host convention. User symbols are prefixed by
`nx_user_`, except the C entry point `main`; runtime helpers use `nx_rt_`.
This is an internal ABI and is not a supported external-function interface.

Strings live for the process lifetime. Locals use stack slots allocated once
per function invocation. Local `int[N]` arrays use `[N x i32]` stack storage and copy by value.
They may be passed and returned by value, without exposed references.
Structs lower to module-local named LLVM aggregate types with primitive or nested struct fields;
they also use value semantics. This calling convention is internal and unstable.
Recursive calls consume additional stack. BoxInt lowers to an owned i32 pointer,
with checked moves and generated scope drops. General heap aggregates, mutable
references, source pointers, lifetime analysis and FFI remain unimplemented. No Rust-equivalent memory-safety claim is made.
Before implementing those features, their aliasing, lifetime and destruction
rules must be specified and enforced in a semantic pass.

## Release and compatibility policy

Versions below 1.0 are experimental. A release must contain source, runtime,
requirements, language rules, known limits, examples, and tests. Language or ABI
changes must be described in the README. Existing language behavior should be
covered by regression tests. A 1.0 compatibility commitment requires a frozen
specification and validated supported targets; neither is complete today.

## Validation scope

The suite combines front-end unit tests, CLI diagnostics and file-preservation
checks, native behavior at `-O0` and `-O3`, 400 deterministic malformed-input
samples, and 40 generated arithmetic expressions checked against a reference.
These are bounded regression checks, not a substitute for coverage-guided
fuzzing, a full interpreter, platform validation, or a security audit.

## Nested layout validation

The analyzer gathers named definitions, resolves field types, rejects cycles,
and computes conservative size/depth limits before code generation. The backend
predeclares all identified LLVM struct types before setting their bodies, allowing
forward references. Nested writes lower to GEP paths rooted in a named local
stack slot. No escaping pointer or source reference is introduced.

## Module lowering

Canonical source paths identify unique units. The loader first resolves every
reference against unmodified declarations, then qualifies names and merges typed
syntax for semantic analysis. Imported qualified symbols use a length-prefixed
LLVM name scheme separate from root `nx_user_` symbols. There is still one linked
LLVM module and runtime, not separate compilation or a stable library ABI.

## Version 0.12 ownership update

`BoxInt`, `box`, `read_box` and `write_box` now implement restricted unique heap ownership, moves and automatic drops. General references, owned aggregate fields and lifetime checking remain unfinished. `OWNERSHIP_DESIGN.md` defines the implemented subset and its conservative control-flow restrictions.

## Version 0.13: reachable ownership paths

Branch joins intersect ownership availability only for paths reaching the same
continuation. Loop bodies may move outer owners if every normal backedge and
`continue` reinitializes the owners available at the header. Break states merge
at the nearest loop exit; return states exit the function. Loop conditions still
cannot move outer owners. Zero-iteration exits remain conservatively possible.
See `OWNERSHIP_DESIGN.md` for the invariant and `examples/ownership_flow.nx`
for an executable example. General references and lifetime checking remain open.
