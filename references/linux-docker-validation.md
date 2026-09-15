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
compiler, pkg-config, Meson/Ninja, Hatchling, curl, git, and unzip. It does not
contain a target plugin. Rebuild it only when the declared baseline changes;
reuse it for each plugin test.

VapourSynth R79's Linux wheel is tagged `manylinux_2_27_x86_64`, so a release
plugin intended for that runtime must not claim a lower end-to-end runtime
floor. A plugin may have lower GLIBC symbol requirements, but that does not
make an incompatible VapourSynth runtime usable.

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
  'mkdir /release && curl -fsSL https://github.com/RyougiKukoc/vapoursynth-tcomb-api4/releases/download/v4.4/tcomb-linux-x86_64.zip -o /release/tcomb.zip && python tools/ci_smoke_package.py --artifact-zip /release/tcomb.zip --json'
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

## TComb evidence

TComb v4.4 established this procedure with the uploaded
`tcomb-linux-x86_64.zip`: explicit loading of `tcomb.so` succeeded under R79,
frames 0, 3, and 11 from a static YUV420P8 case had the same SHA-256,
dimensions were 64x48, and an RGB input was rejected. Its CI repeats the same
asset smoke after manylinux build and before tag publication.

This is a Linux runtime/package behavior gate. It is not an API3/API4
equivalence claim. When an API3 binary/environment is available, run the
separate-process comparison described in `verification.md` and retain both
reports.
