# Algorithmic acceleration of the periodic checksum

Measured 2026-10-25 on Apple M4, macOS-26.6.2-arm64-arm-64bit-Mach-O, Apple clang version 21.0.0 (clang-2100.0.123.102),
Python 3.14.8, using NOVA-X 0.8 at `-O3` for both implementations.

## Result and scope

For the existing checksum problem, a periodic-sum algorithm replaces the linear
loop. The pure calculation exceeds the requested 1000x target in this local test.
Whole-program time improves by **7.79x**, because process startup
and output remain. These are different measurements and must not be conflated.

| Measurement | Linear version | Periodic version |
| --- | ---: | ---: |
| Function calls inside an existing process, median | 13.764706 ms/call | 1.611 ns/call |
| Entire executable, including launch and output | 16.029 ms | 2.057 ms |

The recorded function-call ratio is 8544200x. The very small fast
per-call average is a batched microbenchmark result, including harness-loop,
call and volatile-store overhead; it is not a standalone application latency or
a portable performance guarantee. The robust conclusion is that the arithmetic
work for this fixed periodic problem falls far beyond the 1000x threshold for
large iteration counts. Smaller counts have smaller or no gains.

## Mathematical basis

The fixed period is `[1,3,5,7,11,13,17,19]`, whose sum is 76. For `n = 8*q + r`:

```text
checksum(n) = (76*q + sum(first r elements)) % 1000003
```

The new NOVA-X code computes the period sum with eight iterations and the tail
with at most seven. LLVM additionally simplifies the fixed-size loop. The slow
version performs n iterations. Both functions accept 0 through 20,000,000 and
return -1 for other signed i32 inputs.

All elements are nonnegative. Within the supported domain the unreduced total
is at most 190,000,000, below the i32 maximum. Therefore regrouping the additions
and delaying remainder preserves the original checked-integer result without
introducing overflow. The original per-step sum also remains in range. This is
a problem-specific algorithmic proof, not an automatic general compiler rewrite.
The array and modulus are deliberately fixed and documented.

## Correctness and timing method

- 4,096 consecutive inputs, 64 seeded random inputs over the supported domain,
  and 5 boundary/invalid inputs were compared: **4,165 matches**.
- Both return 999433 for n=20,000,000.
- Function timing uses 9 samples after warmup. Each slow batch has 17 calls and
  each fast batch has 17,000,000 calls. Both use the same repeating input sequence
  `20,000,000 - i%17`; order alternates between samples.
- Kernels are compiled into a separate object, without LTO. The C timing harness
  calls their external symbols and stores each result into a volatile sink.
  Generated assembly was inspected to confirm both function calls remain in
  the timing loops. Dynamic function inputs prevent simply timing a precomputed
  printed answer in this measurement.
- End-to-end timing separately uses 11 seeded/interleaved subprocess runs per
  executable and captures stdout. The fast fixed-input main can be constant-folded;
  this is normal and is distinct from the dynamic-input kernel timing.
- Times use a monotonic clock. CPU load, frequency and thermals were not controlled.
  Raw samples and visible outliers are preserved in the JSON files.

## Reproduce

Extract `benchmark-periodic-1000x.zip`. Activate the NOVA-X Python environment
and use a Mac with Clang available:

```bash
python build_and_run.py --compiler /path/to/nova-x/src/novax.py
python measure_process.py --compiler /path/to/nova-x/src/novax.py
```

The build script imports internal compiler APIs to rename the generated main
symbol for the test-only C harness. This does not introduce a supported source
FFI or library feature. The ordinary NOVA-X example also runs through the CLI:

```bash
python /path/to/nova-x/src/novax.py periodic_checksum.nx -O3 -o periodic
./periodic
```

The benchmark writes build intermediates next to the scripts. Metadata collection
uses macOS `sysctl`; adapt that before testing another OS. The compiler itself
remains version 0.8. The new algorithm is also in `examples/periodic_checksum.nx`.
