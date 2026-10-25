# What remains before a complete systems-language release

NOVA-X is still experimental. Version 0.15 is not a completed C++/Rust alternative.
This is a status checklist, not a claim that every feature below is implemented.

| Area | Current state | Remaining work |
| --- | --- | --- |
| Primitive types | int32, bool, static UTF-8 str | More integer widths, floats, characters, conversion/layout rules |
| Aggregates | Fixed int arrays, nested structs, value calls/returns | Array fields, more element types, enums, slices |
| Memory | Stack/value copies, static text, unique BoxInt and Text heap owners with moves/drops | General owned values, references, lifetimes and checked borrows |
| Modules | Relative files, aliases, public names, qualified types/calls | Packages, separate compilation, field visibility, reproducible builds |
| Standard library | print, len, Boolean conversions, integer console input, owned UTF-8 text and concatenation | Text input, file I/O, collections, process/environment APIs |
| Error handling | Compile diagnostics and terminating runtime checks | A language-level recoverable error model |
| Tooling | Native/LLVM builds, unit/integration and bounded differential tests | CI, platform matrix, coverage-guided fuzzing, formatter, LSP, debug info |
| Speed | Specific measured optimizations and algorithm examples | Broader reproducible workloads and regression monitoring |
| Compatibility | Experimental pre-1.0 behavior | Frozen feature scope, language specification, ABI/release policy |

## Next work order

1. Stabilize module rules and add automated CI for the declared target set.
2. Extend BoxInt ownership to general owned values with explicit control-flow dataflow analysis.
3. Implement and test moves/drops before adding source references.
4. Build strings, I/O and collections on that memory/error model.
5. Expand primitive/aggregate types and validate all promised features and targets.

The user has selected checked ownership with automatic reclamation; see
`OWNERSHIP_DESIGN.md`. This choice constrains future implementation, but does not
turn today's value-copy rules into a borrow checker. A 1.0 label must wait for
an agreed feature scope and verified acceptance criteria.

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

## Version 0.14 input update

Integer console input and EOF-controlled loops are implemented with `read_int`
and `try_read_int`. Text/file I/O and recoverable parse errors remain unfinished.

## Version 0.15 text update

Owned dynamic immutable UTF-8 text is implemented with explicit borrowing
operations, moves and automatic destruction. General references and lifetime
checking, owned aggregate fields, text input, file APIs, more primitive types and
automated cross-platform validation are still required before a full systems
language can be claimed. No 1.0 or Rust-equivalent safety claim is made.
