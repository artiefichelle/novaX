# NOVA-X 0.7 performance measurement

Measured on 2026-10-25, Apple M4, macOS 26.6.2 ARM64, Apple Clang 21.0.0,
Python 3.14.8, llvmlite 0.48.0. This report measures one workload only.

## Workload and method

20,000,000 iterations read an eight-element integer array, accumulate a checksum,
and take a remainder. NOVA-X uses checked addition and checked array accesses.
The C reference explicitly checks addition overflow and array bounds, with the
same input, output, signed integer widths, and loop structure. Divisors are
constant positive values, so division-by-zero and signed division overflow are
impossible in this particular workload.

Each executable was run once to warm it up and then seven times. Reported runtime
is the median wall time for the whole process, including process launch and
output capture. Variants ran sequentially, not interleaved. Load, thermal state,
and frequency were not controlled. Every measured run returned checksum 999433.
This is a bounded comparison, not a statistical equivalence study or a general
language benchmark.

| Variant | Median runtime | Min–max | Single compile invocation |
| --- | ---: | ---: | ---: |
| NOVA-X -O0 | 67.35 ms | 64.36–68.91 ms | 124.22 ms |
| NOVA-X -O3 | 57.84 ms | 57.52–59.90 ms | 110.90 ms |
| C -O0 | 129.03 ms | 128.66–130.04 ms | 41.34 ms |
| C -O3 | 57.82 ms | 57.48–59.54 ms | 42.40 ms |

At `-O3`, NOVA-X and the C reference both took approximately 58 ms here; the
observed difference is much smaller than the variation across samples. There
is no evidence of a NOVA-X speed advantage in the optimized comparison.

The unoptimized C variant calls a separate overflow-check helper, while NOVA-X
emits inline LLVM overflow intrinsics. Its slower `-O0` result is specific to
this implementation and should not be used to rank the languages.

Compilation was measured only once per variant. NOVA-X compilation includes
Python startup, frontend/LLVM work, Clang, and compiling/linking its C runtime;
the C measurement invokes Clang on one source file. These are end-to-end build
measurements, not isolated frontend timings.

## Reproduce

Download and extract `benchmark-nova-x-v0.7.zip`. Use the Python virtual environment
with NOVA-X's requirements installed and a Clang toolchain on PATH:

```bash
python run.py --compiler /path/to/nova-x/src/novax.py
```

The script rebuilds four executables next to itself, checks all outputs, prints
the samples, and writes `results.json`. Its CPU metadata command currently uses
macOS `sysctl`; port that line before running the script on another OS.

The bundle contains `checksum.nx`, `checksum.c`, `run.py`, raw `results.json`, and
this report. More workloads (calls, recursion, branches, memory access patterns,
text operations, larger programs) are needed before broader conclusions.
No speedup over C++ or Rust is established by this measurement.
