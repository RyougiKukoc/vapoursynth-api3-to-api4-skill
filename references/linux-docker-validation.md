# Linux Docker Validation

Use this reference for Linux plugin validation after a VapourSynth API4 port
or a Release-backed packaging change. The baseline image is deliberately ready
for validation but contains no target plugin.

## Baseline image

Build the image from `assets/linux-validation/Dockerfile`. When the host needs
an HTTP proxy, pass it as build arguments rather than attempting a direct
image/dependency download first:

```powershell
docker build `
  --build-arg HTTP_PROXY=http://host.docker.internal:7890 `
  --build-arg HTTPS_PROXY=http://host.docker.internal:7890 `
  -t vpy-api4-vs79-validation `
  -f skills/vapoursynth-api3-to-api4-skill/assets/linux-validation/Dockerfile .
```

The image contains Debian Bookworm, Python 3.13, VapourSynth R79, a native
compiler, CMake, pkg-config, Meson/Ninja, Hatchling, curl, git, and unzip. It does not
contain a target plugin. Rebuild it only when the declared baseline changes;
reuse it for each plugin test.

The examples deliberately mount a repository read-only. Copy the source into a
container work directory before running a build or a command that can create
`__pycache__`; alternatively set `PYTHONDONTWRITEBYTECODE=1` for a read-only
static check. Do not make the source mount writable merely to accommodate
generated build output.

VapourSynth R79's Linux wheel is tagged `manylinux_2_27_x86_64`, so a release
plugin intended for that runtime must not claim a lower end-to-end runtime
floor. A plugin may have lower GLIBC symbol requirements, but that does not
make an incompatible VapourSynth runtime usable.

When a native build obtains headers and `vapoursynth.pc` from the installed
wheel, prepend `vapoursynth/pkgconfig` to `PKG_CONFIG_PATH` while retaining any
caller-provided entries. Do not treat a pre-existing path as proof that it
contains `vapoursynth.pc`; hosted CI environments commonly set it for Python
or unrelated libraries.

Some Linux VapourSynth wheels keep `VapourSynth4.h` and `VSHelper4.h` directly
under `vapoursynth/include`, while legacy cross-platform plugin source uses
`#include <vapoursynth/VapourSynth4.h>`. Confirm the actual header layout as
well as the pkg-config include flag. If these forms differ, create a temporary
build-only include root containing `vapoursynth/` with the wheel headers (or
add an equivalent compatible include directory). Do not mutate the installed
wheel and do not change Windows-only SDK shims merely to make a Linux fallback
compile.

An R79 wheel may be too new to install into a conservative manylinux builder
even though its extracted headers and `vapoursynth.pc` are sufficient to build
a plugin. In that CI-only situation, download and extract the selected wheel,
point `PKG_CONFIG_PATH` at the extracted metadata, and invoke the frontend's
explicit no-isolation dependency-check bypass. Keep `VapourSynth` in
`build-system.requires` and separately test an ordinary isolated PEP 517
install on an R79-capable runtime; the CI bypass is not evidence that users'
isolated source builds can omit the SDK requirement.

Manylinux images can expose a versioned Python interpreter while omitting that
interpreter's `bin` directory from `PATH`. After installing Meson with
`$PYTHON -m pip install meson`, invoke it as
`$PYTHON -m mesonbuild.mesonmain` (or explicitly prepend the scripts
directory) instead of assuming a bare `meson` command is available. Test this
inside the selected builder image before making it the release path.

Before committing to a conservative builder, run its Meson configure step
against the project's declared `cpp_std` or `c_std`. An older builder compiler
can reject a newly named language mode (for example, GCC 10 rejects Meson's
`c++23` option even when the source only needs C++20). Use the oldest standard
that the project actually requires, keep the version change reviewable, and
repeat the ABI inspection after the adjustment.

For a plugin with optional OpenMP, regard `libgomp` as a runtime dependency,
not merely a build detail. Smoke the uploaded payload in fresh processes with
more than one OpenMP thread before bundling a libgomp copy. If that combination
is unstable across the conservative builder and modern runtime, explicitly
disable the optional OpenMP path for the Linux release and Linux fallback,
document the serial-performance tradeoff, and verify its frame output rather
than shipping a runtime library that only passes a loader check.

## Release payload gate

For a Linux Release zip, validate the actual uploaded asset, not a local build
directory. Run the target repository's explicit package smoke script in the
baseline image. The script must disable plugin autoloading before calling
`core.std.LoadPlugin` on the extracted `.so`.

```powershell
$repo = (Resolve-Path repos/vapoursynth-tcomb-api4).Path
docker run --rm `
  -e http_proxy=http://host.docker.internal:7890 `
  -e https_proxy=http://host.docker.internal:7890 `
  -v "${repo}:/workspace:ro" `
  vpy-api4-vs79-validation bash -lc `
  'mkdir /release && curl -fsSL https://github.com/RyougiKukoc/vapoursynth-tcomb-api4/releases/download/v4.2/tcomb-linux-x86_64.zip -o /release/tcomb.zip && python tools/ci_smoke_package.py --artifact-zip /release/tcomb.zip --json'
```

The direct package smoke should prove all of the following:

- the zip has one top-level plugin directory, a manifest, and the expected
  native `.so`;
- explicit `LoadPlugin` succeeds with autoload disabled;
- a deterministic valid clip renders representative frames, recording hashes,
  dimensions, format, and PlaneStats;
- an unsupported input follows the documented error path.

For a Release-backed VCS package, run a second clean-container install using
the documented `git+https` ref. Inspect pip output to confirm the hook selected
the platform Release asset rather than silently compiling from source, then
run the installed-wheel autoload smoke.

## CUDA RTC payloads

Validate each CUDA dependency line in a separate environment. Do not install
or merge payloads built for two CUDA lines into one plugin directory. A Linux
CUDA Release payload should record its toolkit version, `readelf` GLIBC and
GLIBCXX requirements, `ldd` dependencies, NVIDIA driver, GPU name, and compute
capability. A loader-only smoke is insufficient: invoke the RTC filter and
request frames so NVRTC actually compiles the generated kernel on the target
driver and GPU.

When a CUDA plugin statically links `libstdc++` or `libgcc` to keep a portable
ABI, hide archive symbols from the dynamic export table, for example with
`-Wl,--exclude-libs,ALL` on ELF. Otherwise those symbols can interpose with the
host C++ runtime already loaded by VapourSynth or Python and corrupt seemingly
unrelated operations such as generated NVRTC source construction. Recheck both
the ABI inspection and the real RTC compile-and-frame smoke after changing
link options.

## TComb evidence

TComb v4.2 established this procedure with the uploaded
`tcomb-linux-x86_64.zip`: explicit loading of `tcomb.so` succeeded under R79,
frames 0, 3, and 11 from a static YUV420P8 case had the same SHA-256,
dimensions were 64x48, and an RGB input was rejected. Its CI repeats the same
asset smoke after manylinux build and before tag publication.

This is a Linux runtime/package behavior gate. It is not an API3/API4
equivalence claim. When an API3 binary/environment is available, run the
separate-process comparison described in `verification.md` and retain both
reports.
