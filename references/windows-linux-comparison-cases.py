"""Deterministic CPU cases for paired R73/API3 and R74+/API4 comparisons.

Use with ``scripts/run_vs_compare_case.py --case-id <name>``. Every case
uses only a plugin namespace and functions available in the legacy Windows
R73 baseline as well as the API4 Release payload. Accelerator and model
runtime cases belong in target-owned tests because a valid result also needs
the matching device, driver, model, and runtime payload.
"""

import atexit
import base64
import hashlib
import os
import tempfile
from pathlib import Path

import vapoursynth as vs


# quietvoid/dovi_tool's MIT-licensed fel_orig.bin fixture. The file is kept
# alive until this one-plugin process exits because MapNLQ indexes it on frame
# request rather than at node creation.
PROFILE7_RPU_BASE64 = (
    "AAAAARkICQhAYTZQriAAIAgCAIAgCAIAf4Af/AD/wAH/+gAAAwEAAAMA0AAACAAABoAAAEAAADQAAAMCAAADAaAAABAAAA0AAAMAgAAAaAAABAAAAwNAAAAgAAAKhtnmey+GPvwYnmAp6YwGuMVmp81fjf/LbYw544qZgbhspnkPQF9DTLfYDp4Ew0n9O7d+ws1d46FH1EwKLoBiFkoCm11ZUA7Tj1jEbE7BOhRYLP8wI1NtV7u25BFIO5KWZBNpj85rwxvWIPrdQFu+9GQxYLHwG/Lu+/Kl4vPMtKvzzDmDd551aDEbAEgAAEAEAEAAAEASAAAQAQAQAAAQBIAABABABAAAByVmAAA16iVm+fzrHCVmRMoAAAMBAAADAAgAAAMACAAAAwAcNiJDAYYKXjCOBRQAAAMBpj5a//8AAAMAAAMAAAMAAGAgD4DhUYAwCABZyhIAwCghjfglgAgAYUAAAgIqUSCIBQAAAwACKBFQEgwH0AACDWABXrjynYKA"
)


def temporal_yuv420(core, *, width=64, height=48, length=12):
    frames = []
    for number in range(length):
        frames.append(
            core.std.BlankClip(
                width=width,
                height=height,
                format=vs.YUV420P8,
                length=1,
                color=[48 + number * 8, 96 + number * 3, 160 - number * 2],
            )
        )
    return core.std.Splice(frames)


def bordered_yuv420(core, *, length=12):
    inner = temporal_yuv420(core, width=48, height=32, length=length)
    return core.std.AddBorders(inner, left=8, right=8, top=8, bottom=8, color=[16, 128, 128])


def bifrost_cases(core):
    src = temporal_yuv420(core)
    return {
        "clips": [{"name": "temporal_yuv420", "clip": core.bifrost.Bifrost(src, interlaced=False, blockx=4, blocky=4), "frames": [0, 3, 11]}],
        "errors": [{"name": "rgb_rejected", "call": lambda: core.bifrost.Bifrost(core.std.BlankClip(width=64, height=48, format=vs.RGB24), interlaced=False)}],
    }


def dfttest_cases(core):
    src = bordered_yuv420(core)
    return {
        "clips": [{"name": "temporal_bordered_yuv420", "clip": core.dfttest.DFTTest(src), "frames": [0, 3, 11]}],
        "errors": [{"name": "ftype_5_rejected", "call": lambda: core.dfttest.DFTTest(src, ftype=5)}],
    }


def retinex_cases(core):
    src = core.std.BlankClip(width=64, height=48, format=vs.YUV444P8, length=3, color=[96, 128, 128])
    return {
        "clips": [{"name": "yuv444_msrcp", "clip": core.retinex.MSRCP(src), "frames": [0, 1, 2]}],
        "errors": [{"name": "subsampled_yuv_rejected", "call": lambda: core.retinex.MSRCP(core.std.BlankClip(width=64, height=48, format=vs.YUV420P8, length=1))}],
    }


def smoothuv_cases(core):
    src = bordered_yuv420(core, length=3)
    return {
        "clips": [{"name": "bordered_yuv420", "clip": core.smoothuv.SmoothUV(src, radius=3, threshold=270), "frames": [0, 1, 2]}],
        "errors": [{"name": "rgb_rejected", "call": lambda: core.smoothuv.SmoothUV(core.std.BlankClip(width=64, height=48, format=vs.RGB24, length=1))}],
    }


def tcanny_cases(core):
    src = bordered_yuv420(core, length=3)
    return {
        "clips": [{"name": "bordered_yuv420", "clip": core.tcanny.TCanny(src, opt=1), "frames": [0, 1, 2]}],
        "errors": [{"name": "threshold_order_rejected", "call": lambda: core.tcanny.TCanny(src, t_h=1.0, t_l=1.0)}],
    }


def tcomb_cases(core):
    src = bordered_yuv420(core, length=3)
    return {
        "clips": [{"name": "bordered_yuv420", "clip": core.tcomb.TComb(src), "frames": [0, 1, 2]}],
        "errors": [{"name": "rgb_rejected", "call": lambda: core.tcomb.TComb(core.std.BlankClip(width=64, height=48, format=vs.RGB24, length=1))}],
    }


def tivtc_cases(core):
    src = temporal_yuv420(core, width=64, height=48, length=15)
    return {
        "clips": [
            {"name": "tfm", "clip": core.tivtc.TFM(src, order=1, field=1, mode=1, PP=0), "frames": [0, 3, 11]},
            {"name": "tdecimate", "clip": core.tivtc.TDecimate(src, mode=0, cycle=5, cycleR=1), "frames": [0, 3, 11]},
        ],
        "errors": [{"name": "rgb_rejected", "call": lambda: core.tivtc.TFM(core.std.BlankClip(width=64, height=48, format=vs.RGB24, length=1), order=1)}],
    }


def miscfilters_cases(core):
    src = temporal_yuv420(core, length=5)
    return {
        "clips": [
            {"name": "averageframes", "clip": core.misc.AverageFrames([src, src], weights=[1.0, 1.0], scale=2.0), "frames": [0, 2, 4]},
            {"name": "scdetect", "clip": core.misc.SCDetect(src, threshold=0.1), "frames": [0, 2, 4]},
        ],
        "errors": [{"name": "threshold_1_1_rejected", "call": lambda: core.misc.SCDetect(src, threshold=1.1)}],
    }


def dfttest2_cpu_cases(core):
    src = bordered_yuv420(core, length=5)
    # The native DFTTest2 entrypoint deliberately exposes the generated
    # window/spectrum arrays; its Python helper normally supplies these.
    output = core.dfttest2_cpu.DFTTest(
        src,
        window=[1.0] * 256,
        sigma=[1.0] * 144,
        sigma2=1.0,
        pmin=0.0,
        pmax=1.0,
        filter_type=0,
        radius=0,
        block_size=16,
        block_step=16,
        zero_mean=False,
    )
    return {
        "clips": [{"name": "temporal_bordered_yuv420", "clip": output, "frames": [0, 2, 4]}],
        "errors": [],
    }


def knlmeanscl_cases(core):
    src = bordered_yuv420(core, length=3)
    return {
        # ``auto`` selects the RTX OpenCL device in the Windows baseline and
        # the available PoCL CPU device in the Linux validation container.
        "clips": [{"name": "auto_opencl_yuv420", "clip": core.knlm.KNLMeansCL(src, d=1, a=1, s=1, h=1.2, device_type="auto"), "frames": [0, 1, 2]}],
        "errors": [{"name": "h_zero_rejected", "call": lambda: core.knlm.KNLMeansCL(src, h=0)}],
    }


def nnedi3cl_cases(core):
    src = core.std.BlankClip(width=128, height=96, format=vs.YUV420P8, length=3, color=[96, 128, 128])
    return {
        "clips": [{"name": "opencl_double_height", "clip": core.nnedi3cl.NNEDI3CL(src, field=1, dh=True), "frames": [0, 1, 2]}],
        "errors": [{"name": "field_2_double_height_rejected", "call": lambda: core.nnedi3cl.NNEDI3CL(src, field=2, dh=True)}],
    }


def bm3dcuda_rtc_cases(core):
    src = core.std.BlankClip(width=16, height=16, format=vs.YUV444PS, length=3, color=[0.5, 0.5, 0.5])
    return {
        "clips": [{"name": "cuda_yuv444ps", "clip": core.bm3dcuda_rtc.BM3D(src, sigma=[1.0, 1.0, 1.0], radius=0), "frames": [0, 1, 2]}],
        "errors": [],
    }


def vsmlrt_openvino_cases(core):
    model_path = Path(os.environ.get("VS_COMPARE_MODEL_PATH", ""))
    if not model_path.is_file():
        raise RuntimeError("VS_COMPARE_MODEL_PATH must name a readable ONNX model")
    src = core.std.BlankClip(width=16, height=16, format=vs.GRAYS, length=3, color=[0.25])
    return {
        "clips": [{"name": "openvino_cpu_identity", "clip": core.ov.Model(src, str(model_path), device="CPU"), "frames": [0, 1, 2]}],
        "errors": [],
    }


def fft3dfilter_cases(core):
    src = bordered_yuv420(core, length=12)
    return {
        "clips": [{"name": "temporal_bordered_yuv420", "clip": core.fft3dfilter.FFT3DFilter(src), "frames": [0, 3, 11]}],
        "errors": [{"name": "bt_6_rejected", "call": lambda: core.fft3dfilter.FFT3DFilter(src, bt=6)}],
    }


def cfl_cases(core):
    src = core.std.BlankClip(width=64, height=48, format=vs.YUV420P8, length=12, color=[96, 112, 144])
    return {
        "clips": [{"name": "yuv420_to_yuv444", "clip": core.cfl.KACFL(src), "frames": [0, 3, 11]}],
        "errors": [{"name": "rgb_rejected", "call": lambda: core.cfl.KACFL(core.std.BlankClip(width=64, height=48, format=vs.RGB24, length=1))}],
    }


def vsnlq_cases(core):
    rpu = base64.b64decode(PROFILE7_RPU_BASE64)
    expected = "b2b27714b7279c4e24d1a795cb6f95d3ad06745db96d360698ee0932184117a0"
    if hashlib.sha256(rpu).hexdigest() != expected:
        raise RuntimeError("embedded profile-7 RPU fixture hash mismatch")
    handle = tempfile.NamedTemporaryFile(prefix="vsnlq-rpu-", suffix=".bin", delete=False)
    rpu_path = Path(handle.name)
    try:
        handle.write(rpu * 3)
    finally:
        handle.close()
    atexit.register(lambda: rpu_path.unlink(missing_ok=True))
    bl = core.std.BlankClip(format=vs.YUV420P16, width=64, height=32, length=3, color=[4096, 32768, 32768])
    el = core.std.BlankClip(format=vs.YUV420P10, width=64, height=32, length=3, color=[64, 512, 512]).std.SetFrameProp(prop="DolbyVisionRPU", data=rpu)
    float_el = core.std.BlankClip(format=vs.YUV420PS, width=64, height=32, length=1, color=[0.0625, 0.5, 0.5]).std.SetFrameProp(prop="DolbyVisionRPU", data=rpu)
    return {
        "clips": [{"name": "profile7_rpu", "clip": core.vsnlq.MapNLQ(bl, el, str(rpu_path)), "frames": [0, 1, 2]}],
        "errors": [{"name": "float_el_rejected", "call": lambda: core.vsnlq.MapNLQ(bl[:1], float_el, str(rpu_path))}],
    }


CASES = {
    "bifrost": bifrost_cases,
    "dfttest": dfttest_cases,
    "retinex": retinex_cases,
    "smoothuv": smoothuv_cases,
    "tcanny": tcanny_cases,
    "tcomb": tcomb_cases,
    "tivtc": tivtc_cases,
    "miscfilters": miscfilters_cases,
    "dfttest2_cpu": dfttest2_cpu_cases,
    "knlmeanscl": knlmeanscl_cases,
    "nnedi3cl": nnedi3cl_cases,
    "bm3dcuda_rtc": bm3dcuda_rtc_cases,
    "vsmlrt_openvino": vsmlrt_openvino_cases,
    "fft3dfilter": fft3dfilter_cases,
    "cfl": cfl_cases,
    "vsnlq": vsnlq_cases,
}


def make_cases(core, plugin_path):
    del plugin_path
    try:
        return CASES[CASE_ID](core)
    except KeyError as exc:
        raise RuntimeError("unknown CASE_ID {!r}; choices: {}".format(CASE_ID, ", ".join(sorted(CASES)))) from exc
