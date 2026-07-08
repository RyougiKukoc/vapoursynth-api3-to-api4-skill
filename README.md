# VapourSynth API3 to API4 Skill

Codex skill for migrating legacy VapourSynth API3 C/C++ plugin projects to
API4, including build-system retargeting, verification workflow, and optional
Release-backed pip packaging patterns.

This repository's root is the skill directory. `SKILL.md` is the entry point
Codex reads, `references/` contains on-demand guidance, and `scripts/`
contains deterministic helper tools used by the skill.

## Install

Install by cloning this repository directly into your Codex skills directory:

```powershell
git clone https://github.com/RyougiKukoc/vapoursynth-api3-to-api4-skill.git `
  "$HOME/.codex/skills/vapoursynth-api3-to-api4"
```

If `CODEX_HOME` is set, use:

```powershell
git clone https://github.com/RyougiKukoc/vapoursynth-api3-to-api4-skill.git `
  "$env:CODEX_HOME\\skills\\vapoursynth-api3-to-api4"
```

You can also install from GitHub with Codex's skill installer script because
the repository root itself is the skill directory:

```powershell
python install-skill-from-github.py `
  --repo RyougiKukoc/vapoursynth-api3-to-api4-skill `
  --path . `
  --name vapoursynth-api3-to-api4
```

Restart Codex after installation so it picks up the new skill.

## Update

If you installed by `git clone`, update in place:

```powershell
git -C "$HOME/.codex/skills/vapoursynth-api3-to-api4" pull --ff-only
```

Or, with `CODEX_HOME`:

```powershell
git -C "$env:CODEX_HOME\\skills\\vapoursynth-api3-to-api4" pull --ff-only
```

## Validate

From the repository root:

```powershell
python scripts/self_test.py
python quick_validate.py <path-to-skill>
```

Use the `quick_validate.py` script from the system `skill-creator` skill when
you want schema/frontmatter validation in addition to the skill's own
`self_test.py`.
