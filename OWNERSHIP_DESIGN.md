# Ownership in NOVA-X 0.12

The chosen direction is automatic reclamation with checked ownership, similar
in intent to Rust. Version 0.12 implements a restricted unique owner, not a
general borrow checker or Rust-equivalent safety guarantee.

## Implemented subset

- `BoxInt` uniquely owns one heap-allocated signed i32; `box(int)` creates it.
- `read_box(name)` reads without moving. `write_box(name, int)` requires a mutable
  named owner and returns the stored integer. Neither operation produces an
  escaping reference. The write value cannot move the owner being accessed.
- Binding initialization, assignment, argument passing and returns move BoxInt.
  A moved binding cannot be read or moved again. A mutable binding can be
  reinitialized. `owner = owner` is valid and preserves its allocation.
- Owners drop in reverse declaration order at normal scope exit. Return drops
  active owners after evaluating the result; break/continue drop exited loop
  scopes. Assignment evaluates its RHS before dropping the old owner. Discarded
  owned expression results are dropped. Function parameters are owners too.
- Generated owner slots become null on moves; null drops are harmless.
- Branch analysis checks each branch from the same initial state, then requires
  availability on both paths, conservatively even if one path returns.
- Moving an outer owner inside a loop, including its condition, is rejected.
  Loop-local owners can move. Initialization inside a loop is not definite after
  the loop because it might execute zero times.
- BoxInt cannot be printed or compared directly or stored in arrays/structs.
  Primitives, static strings and existing aggregates retain copy semantics.
- Allocation failure and invalid internal pointers terminate with a diagnostic.
  Runtime errors terminate the process without unwinding owners; the operating
  system reclaims process memory. No exceptions or user destructors exist.

## Still required

General owned types and aggregate moves, source shared/exclusive references,
lifetime/escape checks, a control-flow dataflow analysis permitting safe
loop-carried ownership, destructors and a defined native FFI boundary.
No tracing garbage collector is introduced.

## Validation

Compile-fail tests cover use after move, duplicate arguments, invalid mutations,
branch joins, loop moves, zero-iteration initialization and write-value moves.
Native tests run at O0/O3. An instrumented runtime counts live allocations across
normal exits, early returns, overwritten values, moved parameters, discarded
results, break and continue; AddressSanitizer additionally checks those runs.
Validation currently covers macOS ARM64 only.
