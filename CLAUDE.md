# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

> **This is an agent-team configuration project, not a product.** The deliverable is a Claude Code plugin that defines a team of agents (prompts, skills, commands, templates and helper scripts) which *other* projects install to produce demo videos. There is no app to build or ship here. Work in this repo means changing how the team behaves: an agent's role and rules, a pipeline, a gate, a handoff, a skill, a template or a helper script.
>
> - `example/` is a **test fixture** (a fictional app plus a sample `.demo/` run), not a product to develop. Change it only to support testing the team.
> - Don't run the demo pipelines (`/demo-studio:*`) against this repo or create a `.demo/` workspace here unless you're asked to test the team on `example/`.
> - Judge a change by its effect on agent behaviour: clear ownership, no overlapping roles, consistent contracts between agents, gates kept.

A Claude Code plugin marketplace (`demo-record-teams`, `.claude-plugin/marketplace.json`) shipping one plugin, `plugins/demo-studio/`: 18 agents that turn a product into a narrated, captioned, privacy-safe demo video (web, desktop, Android, iOS). Most of the "code" is Markdown prompts; the only executable code is four stdlib-only Python CLIs in `plugins/demo-studio/scripts/`. `README.md` is the user-facing spec — keep it in sync when behaviour changes.

```
plugins/demo-studio/
├── commands/   /demo-studio:<name> entry points (thin: "Act as demo-director, run pipeline X")
├── agents/     one file per role; demo-director orchestrates, the rest do one job
├── skills/     shared reference loaded by agents (run-kits = roster, pipelines, briefs, handoffs)
├── templates/  copied into the user's .demo/<slug>/ workspace
└── scripts/    config.py  project.py  setup_tools.py  vo.py  (+ tests/, requirements/)
example/        static demo app + a full .demo/ run, used as a reference fixture
```

## Commands

Run from `plugins/demo-studio/`:

```
python -m unittest discover -s scripts/tests            # all tests (stdlib unittest, no deps)
python -m unittest scripts.tests.test_config -v         # one module
python -m unittest discover -s scripts/tests -k test_name   # one test by name pattern
```

No build or lint step. Try the plugin locally with `/plugin marketplace add <repo path>` then `/plugin install demo-studio@demo-record-teams`. Serve the example app with `python -m http.server 5173` inside `example/`.

## Architecture

**Orchestration model.** Only `demo-director` runs pipelines, and only as the *main session* (subagents cannot spawn agents): each `commands/*.md` says "Act as demo-director: read `${CLAUDE_PLUGIN_ROOT}/agents/demo-director.md` and run pipeline X". Specialists return a handoff to the director; they never call each other. Three user gates: G1 (brief + `demo.yaml`), G2 (storyboard + narration, before any recording), G3 (finals + QA, before packaging). Resume state lives in `.demo/STATE.md` (director-owned).

**Pipeline order** (voice is produced *before* scene scripts so pauses fit real audio):

```
brief ─▶ app-map ─▶ storyboard+narration(+localize) ─G2─▶ voice ─▶ scenes(dry-run)
  ─▶ capture ─▶ (blur ∥ timeline) ─▶ (motion ∥ captions ∥ mix) ─▶ render ─▶ QA ─G3─▶ package
```

**Three state files, three ownership rules** — the core invariant agents rely on:

| File | Owner | Enforced by |
|---|---|---|
| `.demo/<slug>/demo.yaml` | user (director records decisions; others read-only) | `config.py` (`SCHEMA`, strict parser, `diff` vs `.demo.applied.json` snapshot) |
| `.demo/<slug>/project.json` | one agent per key | `project.py set --as <agent>` (file lock, wrong writer → exit 4, `--expect-version`) |
| `.demo/STATE.md` | demo-director | convention |

Only two kinds of video file exist: raw clips (`sNN.raw.*`) and finals. Blur, motion, captions and mix are *instructions* in `project.json`, applied in one render pass — never intermediate videos.

**Re-run logic.** `project.py` `OWNERS` and `DOWNSTREAM` define key ownership and the dependency graph (`project.py deps <key>`); `config.py diff` maps `demo.yaml` field changes to the owners to re-run. `/fix` routes a symptom to one owner, then re-runs only dependents.

**Toolkit.** Nothing is pre-installed. Agents run `setup_tools.py --check <feature>`; if missing they return `needs-input` with `--plan` output, the director asks the user, and only `toolsmith` runs `--install` (into `.demo/.venv`, recorded in `.demo/toolkit.json`). Toolkit code always runs via the interpreter from `setup_tools.py --python`, never a hard-coded path. Feature → pip deps live in `scripts/requirements/<feature>.txt`.

## Things to keep consistent when editing

- Agent/command Markdown references scripts as `python ${CLAUDE_PLUGIN_ROOT}/scripts/...`; keep that form.
- Changing a `demo.yaml` field means updating together: `config.py` `SCHEMA`, `templates/demo.yaml` (every field commented with allowed values + default), the README `demo.yaml` section, and any agent that reads it.
- Changing `project.json` keys/owners/deps means updating `project.py` `OWNERS`/`DOWNSTREAM`, the README ownership table, the `media-specs` skill schemas, and the owning agent.
- The agent roster, pipelines, `/fix` routing and handoff format are defined in `skills/run-kits/SKILL.md`; the README tables mirror it.
- Scripts must stay stdlib-only (`vo.py` targets Python 3.9+, the rest 3.10+). Exit codes are part of the agent contract (e.g. `vo.py`: 0 ok, 1 check failed, 2 usage; `project.py`: 4 wrong writer).
- Privacy rule: sensitive data is blurred, never replaced with fake data.
- Pipelines never commit or push.
