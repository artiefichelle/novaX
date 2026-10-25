# NOVA-X 0.8 speed comparison

Measured 2026-10-25 on Apple M4 / macOS 26.6.2 ARM64, Apple Clang 21.0.0,
Python 3.14.8, llvmlite 0.48.0. This is the same 20,000,000-iteration checked
integer-array checksum workload used for 0.7, with unchanged NOVA-X source.

Eleven runs per variant were interleaved in a seeded randomized order after one
warmup per executable. Every run returned checksum 999433. Times include process
launch and output capture; load, thermals and frequency were not controlled.

| Variant | Median | Min–max |
| --- | ---: | ---: |
| NOVA-X 0.7 -O3 | 57.38 ms | 57.05–72.33 ms |
| NOVA-X 0.8 disabled -O3 | 57.45 ms | 57.05–57.79 ms |
| NOVA-X 0.8 -O3 | 16.06 ms | 15.58–16.34 ms |
| C reference -O3 | 57.50 ms | 56.82–58.30 ms |
| C manually reduced -O3 | 15.82 ms | 15.49–16.10 ms |

The 0.8 optimization is **3.57x faster** than 0.7 for this workload
(about 72% less runtime). Disabling it in 0.8 restores the baseline
performance, isolating the effect of the new pass. The single-run compile timings
and every raw sample are included in the JSON; compile speed is not the claim.

## What changed

Interval analysis proves that the checksum before `% 1000003` is nonnegative
and less than twice the divisor. In that case, remainder can be computed by a
comparison and at most one subtraction. The compiler applies this transformation
at `-O2` / `-O3` without changing the NOVA-X source. It still evaluates operands,
checks intermediate arithmetic overflow, and checks array bounds. Unknown ranges,
negative operands, unsafe divisors and complex loops conservatively retain the
existing operation. `--no-range-opt` disables the pass for comparison.

The C reference has equivalent explicit overflow and index checks. A manually
reduced C implementation is included: it reaches approximately the same speed
as optimized NOVA-X. This demonstrates an automatic optimization for a particular
pattern, not a general advantage over C or Rust. Programs without this pattern
may receive no speedup. The baseline has one visible outlier; all samples remain
in the report and the comparison uses medians.

## Reproduce

Download `benchmark-nova-x-v0.8.zip`, extract it, and activate a Python environment
with NOVA-X's requirements. Have Clang on PATH and extract both language releases:

```bash
python run.py --baseline /path/to/v0.7/nova-x/src/novax.py --candidate /path/to/v0.8/nova-x/src/novax.py
```

The script builds both NOVA-X versions, 0.8 with the pass disabled, the original
C reference and the manually reduced C variant. It validates output, records
samples, and writes `results.json`. CPU metadata currently uses macOS `sysctl`.
The bundle includes both C sources, unchanged NOVA-X source, runner, raw results,
and this report. The earlier test remains in `benchmark-nova-x-v0.7.zip`.
