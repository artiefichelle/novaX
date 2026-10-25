# Ownership direction — selected, not implemented

The user selected automatic memory reclamation with checked ownership/lifetimes,
similar in intent to Rust. This document records the direction. NOVA-X 0.11 does
not implement a borrow checker, owned heap objects, destructors or source references.
Current values are primitives, static string pointers and copied fixed aggregates.

## Required semantics before heap/reference syntax is accepted

- Each owned allocation has one owner. Leaving its scope drops it automatically.
- Moving an owned value invalidates the source binding; later use must be rejected.
- Primitive values remain copyable. An aggregate is copyable only if every field
  is copyable. Existing static `str` remains distinct from any future owned string.
- Shared borrows permit reading. An exclusive mutable borrow excludes simultaneous
  access through the owner or other borrows while live.
- References may not outlive the allocation they refer to. Returning a reference
  to a local, storing a short-lived reference into a longer-lived object, or using
  a reference after its owner is moved/dropped must be rejected.
- Drop order, branch joins, loop-carried moves, partially moved aggregates and
  error exits must be specified before code generation is implemented.
- External/native calls require a separate boundary policy; no unchecked FFI is
  implied by the internal LLVM calling convention.

## Implementation stages

1. Specify an owned type and its operations, including allocation failure and drop.
2. Introduce a control-flow IR with binding identities, moves, borrows and drop points.
3. Perform definite-initialization and use-after-move analysis over every CFG path.
4. Define reference regions/lifetimes and enforce aliasing and escape constraints.
5. Lower validated ownership operations to allocation/drop code.
6. Add positive and compile-fail tests for all rules, including branches, loops,
   early returns, nested fields and modules; add memory/runtime tooling checks.

Do not publish a Rust-equivalent memory-safety claim before these rules exist and
are enforced. Automatic garbage collection is not the selected ownership design.
