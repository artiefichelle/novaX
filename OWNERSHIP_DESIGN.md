# Ownership in NOVA-X 0.15

The chosen direction is automatic reclamation with checked ownership, similar
in intent to Rust. Version 0.15 implements a restricted unique owner, not a
general borrow checker or Rust-equivalent safety guarantee.

## Implemented subset

- `BoxInt` uniquely owns one heap-allocated signed i32; `box(int)` creates it.
- `read_box(name)` reads without moving. `write_box(name, int)` requires a mutable
  named owner and returns the stored integer. Neither operation produces an
  escaping reference. The write value cannot move the owner being accessed.
- Binding initialization, assignment, argument passing and returns move BoxInt or Text.
  A moved binding cannot be read or moved again. A mutable binding can be
  reinitialized. `owner = owner` is valid and preserves its allocation.
- Owners drop in reverse declaration order at normal scope exit. Return drops
  active owners after evaluating the result; break/continue drop exited loop
  scopes. Assignment evaluates its RHS before dropping the old owner. Discarded
  owned expression results are dropped. Function parameters are owners too.
- Generated owner slots become null on moves; null drops are harmless.
- Branch analysis checks each branch from the same initial state. Only branches
  that reach the continuation participate in its availability intersection.
- Each loop records its header state. Every reachable normal backedge and
  `continue` must restore all outer owners available at that header. The analysis
  starts each body with the header state, so this invariant holds inductively
  over repeated iterations. Replacing an allocation is allowed; preserving its
  identity is not required.
- `break` records the outer state at that exit and has no backedge requirement.
  Returns leave the function and do not contribute to branch or loop-exit joins.
  Nested transfers target the nearest enclosing loop. Inner locals drop normally.
- The loop-exit state intersects entry availability (possible zero iterations)
  with all break states. Even `while true` retains the conservative entry path;
  no constant-condition reachability proof is performed. A loop cannot make an
  initially moved owner definitely initialized afterward.
- Moves of outer owners in loop conditions remain rejected. Conditions may
  read or update boxed integer contents without transferring ownership.
- Lexical scope identity distinguishes shadowed bindings. Replacing an inner
  variable of the same name cannot repair a moved outer owner.
- Owned BoxInt and Text cannot be printed or compared directly or stored in arrays/structs.
  Primitives, static strings and existing aggregates retain copy semantics.
- Allocation failure and invalid internal pointers terminate with a diagnostic.
  Runtime errors terminate the process without unwinding owners; the operating
  system reclaims process memory. No exceptions or user destructors exist.

## Still required

General owned types and aggregate moves, source shared/exclusive references,
lifetime/escape checks, a general CFG representation beyond the current
structured-control-flow availability analysis, destructors and a defined native
FFI boundary.
No tracing garbage collector is introduced.

## Validation

Compile-fail tests cover use after move, duplicate arguments, invalid mutations,
branch joins, loop moves, zero-iteration initialization and write-value moves.
Native tests run at O0/O3. An instrumented runtime counts live allocations across
normal exits, early returns, overwritten values, moved parameters, discarded
results, break and continue; AddressSanitizer additionally checks those runs.
Validation currently covers macOS ARM64 only.

## Version 0.13 validation

16 additional tests exercise reachable branch joins, replacing owners in loops,
continue backedges, break-state joins, nested loops, shadowing and returned owners.
The native memory test covers these paths at O0/O3 using allocation accounting
and AddressSanitizer. This extends the existing 119-test baseline to 135 tests.

## Owned Text in 0.15

Text has the same unique move/drop discipline as BoxInt. Its bytes are immutable;
clone and concat create fresh owners, while length, byte access, equality and
printing borrow named owners without moving them. The borrow cannot escape the
runtime call; index evaluation is checked for a move of the borrowed owner.
No source reference type or general lifetime/alias checker is introduced.

Cleanup records source ownership per slot, separating static str from Text even
though both use pointer representations. Each Text owns one allocation. Native
O0/O3 tests instrument all malloc/free calls, including mixed BoxInt/Text scopes,
returns, discarded results, loop replacement, break and continue. These tests run
with AddressSanitizer and UBSan and require zero live allocations at normal exit.
