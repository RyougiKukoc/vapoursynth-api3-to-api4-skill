"""Template case file for run_vs_compare_case.py.

Copy this file into a plugin test directory and edit `make_cases` for the
plugin under migration. The same edited file should run in both the R73/API3
and R74+/API4 environments.

Run one fresh Python process per plugin binary. VapourSynth plugins loaded with
core.std.LoadPlugin cannot be unloaded from a live core.
"""

import vapoursynth as vs


def make_sources(core):
    return {
        "yuv420p8_64": core.std.BlankClip(width=64, height=64, format=vs.YUV420P8, length=3, color=[64, 512, 512]),
        "yuv420p8_65x67": core.std.BlankClip(width=65, height=67, format=vs.YUV420P8, length=3, color=[96, 512, 512]),
    }


def make_cases(core, plugin_path):
    src = make_sources(core)

    # Replace `core.namespace.Filter` and arguments with the plugin being tested.
    # The runner hashes frames and adds core.std.PlaneStats for every plane.
    clips = [
        {
            "name": "default",
            "clip": core.namespace.Filter(src["yuv420p8_64"]),
            "frames": [0, 1, 2],
        },
        {
            "name": "planes0",
            "clip": core.namespace.Filter(src["yuv420p8_64"], planes=[0]),
            "frames": [0],
        },
        {
            "name": "odd_dimensions",
            "clip": core.namespace.Filter(src["yuv420p8_65x67"]),
            "frames": [0],
        },
    ]

    errors = [
        {
            "name": "invalid_low",
            "call": lambda: core.namespace.Filter(src["yuv420p8_64"], strength=-1),
        },
        {
            "name": "duplicate_plane",
            "call": lambda: core.namespace.Filter(src["yuv420p8_64"], planes=[0, 0]),
        },
    ]

    return {"clips": clips, "errors": errors}
