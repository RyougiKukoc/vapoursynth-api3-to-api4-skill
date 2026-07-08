# VapourSynth API3 to API4 Skill

Codex skill for migrating legacy VapourSynth API3 C/C++ plugin projects to
API4, including build-system retargeting, verification workflow, and optional
Release-backed pip packaging patterns.

This repository's root is the skill directory. `SKILL.md` is the entry point
Codex reads, `references/` contains on-demand guidance, and `scripts/`
contains deterministic helper tools used by the skill.

## Install

This repository root is itself the skill directory. Any harness that supports a
directory-based `SKILL.md` skill can install this repository as one folder
named `vapoursynth-api3-to-api4`.

### Codex

Preferred in Codex: send Codex a prompt that explicitly asks it to use
`$skill-installer`. This is a prompt for Codex, not a shell command:

```text
Use $skill-installer to install the skill from GitHub repo
RyougiKukoc/vapoursynth-api3-to-api4-skill with path . and name
vapoursynth-api3-to-api4. After installation, tell me whether I need to
restart Codex.
```

Manual fallback: clone this repository directly into your Codex skills
directory:

```powershell
git clone https://github.com/RyougiKukoc/vapoursynth-api3-to-api4-skill.git `
  "$HOME/.codex/skills/vapoursynth-api3-to-api4"
```

If `CODEX_HOME` is set, use:

```powershell
git clone https://github.com/RyougiKukoc/vapoursynth-api3-to-api4-skill.git `
  "$env:CODEX_HOME\\skills\\vapoursynth-api3-to-api4"
```

If you invoke Codex's helper script yourself instead of asking Codex to use
`$skill-installer`, the repository root is still the selected skill path:

```powershell
python install-skill-from-github.py `
  --repo RyougiKukoc/vapoursynth-api3-to-api4-skill `
  --path . `
  --name vapoursynth-api3-to-api4
```

Run that helper from the `skill-installer/scripts` directory, or otherwise make
that directory importable, because the script imports its sibling
`github_utils.py`.

Restart Codex after installation so it picks up the new skill.

### Claude Code

Claude Code also uses directory-based `SKILL.md` skills, so this repository can
be installed directly as a personal or project skill.

Personal skill for all Claude Code projects:

```powershell
git clone https://github.com/RyougiKukoc/vapoursynth-api3-to-api4-skill.git `
  "$HOME/.claude/skills/vapoursynth-api3-to-api4"
```

Project-local skill for only the current repository:

```powershell
git clone https://github.com/RyougiKukoc/vapoursynth-api3-to-api4-skill.git `
  ".claude/skills/vapoursynth-api3-to-api4"
```

If you prefer not to duplicate the checkout, Claude Code also supports
symlinking a skill directory into one of its skill roots.

## Update

If you installed by `git clone`, update in place:

```powershell
git -C "$HOME/.codex/skills/vapoursynth-api3-to-api4" pull --ff-only
```

Or, with `CODEX_HOME`:

```powershell
git -C "$env:CODEX_HOME\\skills\\vapoursynth-api3-to-api4" pull --ff-only
```

For Claude Code personal installs:

```powershell
git -C "$HOME/.claude/skills/vapoursynth-api3-to-api4" pull --ff-only
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
