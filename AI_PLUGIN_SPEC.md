# NOVA-X AI Optimizer Plugin — Proposed v0.1 Protocol

This specification describes a **future** interface; no AI plugin runs in the current compiler.

1. Compiler emits typed, normalized candidate IR and a list of observable invariants.
2. Isolated AI optimizer receives IR, target architecture, budget, and restrictions via JSON (no source filesystem or network access by default).
3. AI returns a proposed IR rewrite and machine-readable explanation, **never executable trusted code**.
4. Compiler re-typechecks, verifies control-flow and effect/ownership constraints, and runs differential tests against the original program.
5. For behavior not fully proven equivalent, candidate remains experimental and requires explicit approval.
6. Benchmark harness runs candidates in a restricted process with reproducible inputs; accept only measured improvements.
7. Audit trail records optimizer identity, prompt/config, source hash, proof/test results and performance data.

Never execute arbitrary plugin output without sandboxing. Functional tests are not formal correctness proofs.
