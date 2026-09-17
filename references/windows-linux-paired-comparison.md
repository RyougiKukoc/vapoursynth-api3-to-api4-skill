# Windows/Linux Paired Comparison

Use this procedure when an API3 Windows baseline and API4 Release payloads
for Windows and Linux are available. It proves behavior across the migration
and across the two published API4 platforms; an API4 load smoke alone does
not do either.

## Evidence Setup

1. Inventory the R73 interpreter, baseline DLL, plugin namespace, callable,
   exact Release tag, and one deterministic valid input. Confirm the baseline
   DLL is actually installed before declaring the comparison unavailable.
2. Download the Windows and Linux zips for that one Release tag. Query the
   Release asset digest with GitHub CLI and compare it to a local SHA-256
   before extracting. When `gh` is not on PATH, use
   `C:\Program Files\GitHub CLI\gh.exe` directly.
3. Use one fresh process for each baseline/API4-Windows/API4-Linux plugin
   load. Pass the native module path to `core.std.LoadPlugin`; do not rely on
   ambient autoload paths or a locally built module.
4. Use `scripts/run_vs_compare_case.py` with a shared case file and a distinct
   `--label` for all three reports. `--case-id` lets a shared case file select
   a target-specific deterministic invocation. Compare API3-to-Windows,
   API3-to-Linux, and Windows-to-Linux with `compare_vs_reports.py`.

The bundled `windows-linux-comparison-cases.py` contains CPU, OpenCL, CUDA,
OpenVINO, and Dolby Vision RPU examples. It is a starting point: keep a case
only when its namespace and arguments match the target's documented ABI.

## Runtime Details

On Windows, keep the extracted payload directory in the DLL search path. The
runner also adds the interpreter, `platlib`, `purelib`, and site-packages
directories because MinGW payloads can depend on runtime DLLs supplied by the
VapourSynth wheel. A successful target-owned smoke that has those paths but a
failure in a narrower generic runner is a runner isolation defect, not missing
Release evidence.

For Linux use the R79 Docker validation image and bind-mount the extracted
payload. Run CUDA payloads with `--gpus all`, check the actual GPU/driver from
inside the container, and request a frame or perform inference. A hosted CI
runner without a driver is not evidence that a local GPU cannot validate a
CUDA payload. Keep CUDA payload versions isolated; do not mix cu121 and cu129
directories or dependency trees.

Docker Desktop can expose CUDA to Linux containers while not exposing a Linux
NVIDIA OpenCL ICD. The optional
`assets/linux-validation/Dockerfile.opencl-validation` adds the OpenCL dispatch
loader and PoCL for CPU OpenCL runtime testing. Record that device choice in
the report. If a plugin rejects a valid ICD, retain its exact error and the
device/runtime details rather than treating load success as an executed OpenCL
test.

## Float Results

Treat integer output hashes as strict. For floating-point or FFT/CUDA paths,
use `--arrays-out` on the same three frame selections and compare contiguous
plane arrays as well as report hashes and PlaneStats. Record byte equality,
maximum absolute error, mean absolute error, and differing-sample count for
every changed plane.

Do not silently call a hash mismatch equivalent. A documented platform result
such as a bounded one-LSB integer difference or a finite CUDA rounding delta
can be accepted only after the raw-array metrics, format, dimensions, frame
properties, and error behavior have also been recorded.

## Completion Record

For each plugin, state one of:

- all three reports match strictly;
- Windows API3/API4 match and the Linux result has quantified, reproducible
  platform-specific numerical differences;
- a specific baseline DLL is unavailable; or
- a specific Linux runtime/device path failed, with the command and error.

Store the reports and extracted-asset digest evidence outside source scanning
directories (for example, `verification-*`) so API3 baselines do not affect
the migration scanner. After changing the runner, case library, or optional
Dockerfile, run `python scripts/self_test.py` before recording the result.

## Observed Platform Cases

These results are reference evidence, not a substitute for testing a new
Release tag:

- BM3DCUDA cu129 ran on the same RTX 3090 Ti in Windows and Linux. The R73
  baseline and API4 Windows output were byte-identical. Linux CUDA output had
  a maximum absolute float32 difference of `2.9802322387695312e-08` and mean
  absolute difference of `2.421438694000244e-08`; preserve it as a quantified
  cross-platform compiler/runtime difference rather than a strict match.
- KNLMeansCL 1.1.2 loaded in the optional PoCL container but failed when
  creating a node with `oclUtilsGetPlaformDeviceIDs: CL_INVALID_VALUE`. Its
  platform-version probe uses a fixed 64-byte buffer while PoCL reports a
  101-byte platform version. API3/API4 Windows on NVIDIA OpenCL matched
  strictly. Keep the Linux failed-node evidence until the utility handles
  variable-length OpenCL info strings and the fixed payload is retested.
- FFT3DFilter R2.1 had no available API3 baseline. Its API4 Windows/Linux
  result differed in 36 chroma samples across the selected frames, with a
  maximum integer difference of one LSB; dimensions, frame properties, and
  documented error behavior matched. CFL 1.0.2 also had no API3 baseline and
  its API4 Windows/Linux report matched strictly.
