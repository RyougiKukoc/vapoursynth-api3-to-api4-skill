# Review an Existing Migration Against Another Implementation

Use this reference when auditing a completed or partial API4 migration against
an upstream release, fork, or packaging PR. The purpose is to find missed
interface changes and behavior risks while preserving the user's supported
backends, CUDA versions, and release design. Reuse existing baseline evidence;
missing runtime hardware can block execution without blocking source review.

## Resolve the Source Behind the Reference

A packaging PR may change only a submodule pointer while the API migration lives
in a different repository. Record the PR state, base/head commits, relevant
`.gitmodules` URL changes, and old/new gitlink hashes. Inspect the plugin source
at those hashes rather than inferring its changes from the superproject patch.
For example:

```bash
git diff --submodule=log BASE HEAD
git show HEAD:.gitmodules
git ls-tree BASE path/to/plugin
git ls-tree HEAD path/to/plugin
```

Read the old `.gitmodules` too when the submodule URL changed. Resolve both
plugin revisions in their actual source repositories; a branch name or the
current tip of a fork may no longer identify the code reviewed by that PR.

For our candidate, record the working-tree revision and local changes, remote
default-branch revision, release-tag revisions, and source revision of any
tested binary. These can contain different backend implementations. Compare
the intended API3 baseline, our candidate, and the reference migration at
explicit revisions. Later source changes need their own evidence.

## Inventory Coverage Before Judging Completeness

For each relevant backend, record:

| Item | Evidence to record |
| --- | --- |
| Interface | Source directory, API3/API4 state, exported namespace/functions |
| Build | Enabled targets, automatic/manual workflows, compiler and dependencies |
| Delivery | Release variant, plugin DLL, Python helper and backend selection |
| Verification | Build, explicit load, first execution, paired output, installed artifact |

Include helpers such as `Version` or device queries when they are public API.
Distinguish migrated but unshipped code, shipped code present only on release
tags, and historical backends explicitly outside the user's scope. Retaining a
default-off API3 backend is not a defect in a scoped port; document its status
and scan maintained targets separately. Conversely, one clean target scan or
one successful CPU smoke does not cover every shipped backend.

## Compare Semantics, Then Classify Differences

Use [migration-guide.md](migration-guide.md) for API mappings and ownership,
request-pattern, format, stride, and property semantics. A zero-marker scan
only removes evidence of legacy names. Read the actual callbacks and error
paths, including create-time validation, resource lifetime, and the dependency
declarations that replace API3 lifecycle code.

Classify each material difference as an equivalent implementation, required
interface fix, independent behavior/optimization change, dependency/build
change, intentional scope difference, or unresolved verification gap. Cite the
source location and explain the effect. A respected reference implementation
is useful evidence, not proof that every difference should be copied.

Replacing runtime compilation with ahead-of-time kernels is a backend design
change even when the VapourSynth signature stays the same. Compare the
supported source customization, compilation options, specialization choices,
kernel/engine caches, supported GPU architectures, and first-use failure paths.
Do not treat NVRTC-to-`nvcc`/fatbin replacement or a new engine format as a
mandatory API4 migration step. Preserve the requested runtime design unless
the user has asked to change it.

## Preserve Fixed CUDA Release Variants

When the user requests several fixed CUDA versions, review each as a separate
release contract. Another project may pin explicit current versions and update
them through Renovate or workflow inputs; that still does not imply it maintains
the same parallel older/newer release variants.

Record these together for each relevant variant:

- Toolkit release and resolved component versions, including NVRTC, cuFFT, and
  link-time components actually used. Read the installed package/build output
  rather than trusting the variant name alone.
- CUDA compiler, host compiler/toolset, language standard, and the actual
  compiler paths selected by the build system. A compatible toolkit pin does
  not pin the compiler supplied by a moving hosted-runner image.
- Dependent inference/runtime versions such as TensorRT, ONNX Runtime, and
  cuDNN; static versus dynamic linkage; bundled support DLLs and delayed loads.
- Requested GPU architectures, generated SASS/PTX or runtime compilation target,
  and the driver/GPU used for execution. New architecture flags may not be
  recognized by an older fixed toolkit. A successful binary load does not prove
  an engine or kernel supports the target GPU.
- Release tag, asset name, wheel/VCS variant selection, and payload identity.
  Test each documented selection path instead of assuming the default variant
  also proves an explicitly selected one.

Keep source/API fixes separate from adopting newer dependency versions, dropping
an older CUDA variant, or narrowing backend/GPU coverage. If a reference change
needs a newer toolkit, adapt the fix to the requested matrix or document the
precise incompatibility rather than silently changing the release target.

Inspect build logs and fallback paths as well as job status. A failed custom
engine-builder compilation may be allowed to fall back to a vendor executable;
report which executable was actually shipped and which custom features were
lost or remain unverified. A successful workflow does not prove that every
optional/custom build succeeded. Preserve a supported compiler/toolset for old
CUDA variants and adapt patches to each dependent SDK version.

## Match Verification Claims to Evidence

Report the tested backend, source commit, toolkit/runtime combination, case,
and artifact for each result. Use [verification.md](verification.md) for the
normal gates, with these distinctions for accelerator backends:

- DLL load checks registration and immediately resolved dependencies. Delayed
  CUDA/inference imports may remain entirely untested.
- A device query or `Version()` call may resolve some runtime libraries, but
  does not exercise kernel compilation, engine construction, or frame processing.
- A first frame must exercise the intended backend's JIT/engine path, using a
  controlled cache state when compilation itself is under review.
- Paired behavior requires the corresponding baseline/candidate and equivalent
  deterministic inputs for that backend. Exact hashes and aggregate statistics
  serve different purposes; follow the comparer limitations in the protocol.

Keep CPU-only, GPU-load-only, first-execution, and paired-output results explicit.
Record unavailable GPU/driver/runtime combinations as unverified, even when all
hosted build jobs pass. Do not generalize one variant's runtime evidence to
another without demonstrating why the tested binary/runtime path is identical.

For release and VCS-install tests, record the downloaded asset hash and source
revision alongside the resolved checkout. An unchanged tag, asset URL, or wheel
filename can refer to a replaced payload. A smoke job that finished before the
new upload proves the earlier asset only. Sequence publication before the
install gate, or establish that the exact immutable tested payload was uploaded.

Close the review with source findings, intentional differences, fixes made, and
verification limits. Completion of the review and completion of every runtime
gate are separate claims; unresolved gates should remain visible.
