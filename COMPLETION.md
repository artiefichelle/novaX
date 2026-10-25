# What remains before a complete systems-language release

NOVA-X is still experimental. Version 0.11 is not a completed C++/Rust alternative.
This is a status checklist, not a claim that every feature below is implemented.

| Area | Current state | Remaining work |
| --- | --- | --- |
| Primitive types | int32, bool, static UTF-8 str | More integer widths, floats, characters, conversion/layout rules |
| Aggregates | Fixed int arrays, nested structs, value calls/returns | Array fields, more element types, enums, slices |
| Memory | Stack/value copies and static text | Owned heap values, moves, drops, lifetimes and checked borrows |
| Modules | Relative files, aliases, public names, qualified types/calls | Packages, separate compilation, field visibility, reproducible builds |
| Standard library | print, len, Boolean conversions | Console input, file I/O, owned text, collections, process/environment APIs |
| Error handling | Compile diagnostics and terminating runtime checks | A language-level recoverable error model |
| Tooling | Native/LLVM builds, unit/integration and bounded differential tests | CI, platform matrix, coverage-guided fuzzing, formatter, LSP, debug info |
| Speed | Specific measured optimizations and algorithm examples | Broader reproducible workloads and regression monitoring |
| Compatibility | Experimental pre-1.0 behavior | Frozen feature scope, language specification, ABI/release policy |

## Next work order

1. Stabilize module rules and add automated CI for the declared target set.
2. Specify owned heap values and an explicit control-flow analysis representation.
3. Implement and test moves/drops before adding source references.
4. Build strings, I/O and collections on that memory/error model.
5. Expand primitive/aggregate types and validate all promised features and targets.

The user has selected checked ownership with automatic reclamation; see
`OWNERSHIP_DESIGN.md`. This choice constrains future implementation, but does not
turn today's value-copy rules into a borrow checker. A 1.0 label must wait for
an agreed feature scope and verified acceptance criteria.
