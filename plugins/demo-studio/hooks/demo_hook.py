#!/usr/bin/env python3
"""demo-studio plugin hooks (docs/redesign §4.3). One script, event taken from the hook input JSON on stdin.

Hook schema checked against https://code.claude.com/docs/en/hooks : plugin `hooks/hooks.json`
({"hooks": {Event: [{matcher, hooks: [{type, command, timeout (s)}]}]}}), input fields `hook_event_name`,
`tool_name`, `tool_input` (Write/Edit: file_path, content | old_string, new_string, replace_all; Bash: command),
`cwd`, `agent_type` (present only inside a subagent or a `--agent` session), SubagentStop `stop_hook_active`,
`agent_type`, `last_assistant_message`. Block = exit 2 with the reason on stderr (PreToolUse: denies the
call; SubagentStop: keeps the subagent running with the reason as its next instruction). MultiEdit is not in
the docs' tool_input tables: handled defensively (file_path + edits[]).

Scope: a call from a subagent that is not a demo-studio agent is never touched (agent_type check). The main
session (no agent_type) is checked only for targets under `.demo/` / commands naming them.

PreToolUse
  Write|Edit|MultiEdit  deny `.demo/**/project.json` (use project.py set --as <owner>; #checks only via checks.py);
                        deny any change of the `privacy.accepted` entries of `.demo/**/demo.yaml`
                        (only `config.py accept`, run by demo-director after the user's answer, may).
  Bash                  deny `project.py ... set checks`; deny sed -i / redirect / tee / cp / mv / python-write
                        on project.json and on demo.yaml `accepted`; deny `config.py accept` from a demo-studio
                        agent other than demo-director. Best-effort on shell text: the code paths
                        (project.py refusing `set checks`, checks.py the only write_checks caller) stay the base.
SubagentStop (demo-studio agents only)
  runs `checks.py dod <agent>` in-process. DoD not met -> exit 2 with the failed items (the agent continues);
  after DEMO_HOOK_MAX_BLOCKS (default 2) blocks for the same agent in a project, the stop is allowed and
  `.demo/<slug>/hook-state.json` marks it `blocked` (demo.py status shows it): no endless fix loop.
  The counter resets when the DoD passes. `stop_hook_active` is not used to stop early: the counter is the
  limit (Claude Code's own cap of 8 consecutive continuations stays as backstop).

Failure policy: privacy-class rules (project.json, #checks, privacy.accepted, config.py accept) FAIL CLOSED:
an exception while evaluating a call that touches those names denies it. Everything else (SubagentStop,
unreadable input, unknown tools) FAILS OPEN (exit 0).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(PLUGIN_ROOT, "scripts")
PLUGIN_NAME = "demo-studio"
DIRECTOR = "demo-director"
DEFAULT_MAX_BLOCKS = 2
SENSITIVE_WORDS = ("project.json", "demo.yaml", "accepted", "config.py", "checks")


def demo_agents():
    d = os.path.join(PLUGIN_ROOT, "agents")
    try:
        return {f[:-3] for f in os.listdir(d) if f.endswith(".md")}
    except OSError:
        return set()


def agent_name(payload):
    t = payload.get("agent_type")
    t = t.strip() if isinstance(t, str) else ""
    return t[len(PLUGIN_NAME) + 1:] if t.startswith(PLUGIN_NAME + ":") else t


def foreign_agent(payload):
    """True when the call comes from an agent that is not a demo-studio agent."""
    name = agent_name(payload)
    return bool(name) and name not in demo_agents()


# =========================================================================== PreToolUse rules
def norm_parts(path):
    return [p.lower() for p in re.split(r"[\\/]+", path or "") if p]


def under_demo(path):
    return ".demo" in norm_parts(path)


def is_project_json(path):
    parts = norm_parts(path)
    return bool(parts) and parts[-1] == "project.json" and ".demo" in parts[:-1]


def is_demo_yaml(path):
    parts = norm_parts(path)
    return bool(parts) and parts[-1] == "demo.yaml" and ".demo" in parts[:-1]


def accepted_value(text):
    """Normalised value of the `accepted:` key (inline value plus block-list lines), '' when empty/absent."""
    m = re.search(r"^([ \t]*)accepted:[ \t]*(.*)$", text or "", re.M)
    if not m:
        return ""
    val = m.group(2).strip()
    if not val.startswith(("[", '"', "'")):
        val = val.split("#", 1)[0].strip()
    block = re.match(r"(?:\r?\n[ \t]+-[^\n]*)*", text[m.end():]).group(0)
    out = re.sub(r"\s+", " ", val + " " + block).strip()
    return "" if out in ("[]", "null", "~", "") else out


def apply_edits(text, edits):
    """Apply Edit/MultiEdit style edits; None when an old_string is not found (cannot tell the result)."""
    for e in edits:
        old, new = e.get("old_string"), e.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or old not in text:
            return None
        text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def read_text(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return None


def rule_file_project_json(payload):
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if is_project_json(path):
        return ("project.json is written only through project.py (project.py set <key> --as <owner>); "
                "#checks only by checks.py / blur.py verify. Direct edits are blocked.")
    return None


MSG_ACCEPTED = ("privacy.accepted may be changed only by `config.py accept` (demo-director, after the user's "
                "answer). Direct edits are blocked.")


def rule_file_accepted(payload):
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if not is_demo_yaml(path):
        return None
    old = read_text(path) or ""
    if payload.get("tool_name") == "Write":
        new = ti.get("content") if isinstance(ti.get("content"), str) else None
        return MSG_ACCEPTED if new is not None and accepted_value(old) != accepted_value(new) else None
    edits = [e for e in (ti.get("edits") if isinstance(ti.get("edits"), list) else [ti]) if isinstance(e, dict)]
    new = apply_edits(old, edits)
    if new is None:   # cannot replay the edit: judge by the text it touches
        touched = "".join(str(e.get("old_string", "")) + str(e.get("new_string", "")) for e in edits)
        return MSG_ACCEPTED if "accepted" in touched.lower() else None
    return MSG_ACCEPTED if accepted_value(old) != accepted_value(new) else None


FILE_RULES = (rule_file_project_json, rule_file_accepted)

WRITE_VERBS = (
    r"\b(?:sed|perl)\b[^|;&\n]*\s-[A-Za-z]*i",
    r">>?\s*['\"]?[^\s'\"|;&<>]*{t}",
    r"\btee\b[^|;&\n]*{t}",
    r"\b(?:cp|mv|install|rm|truncate|dd|ln)\b[^|;&\n]*{t}",
)
SCRIPT_WRITE = (   # one-liners keep `;` inside quotes: tested on the whole command
    r"\b(?:python3?|node|ruby)\b.*{t}.*(?:\.write|write_text|json\.dump|open\([^)]*['\"][wa]\+?['\"])",
    r"\b(?:python3?|node|ruby)\b.*(?:\.write|write_text|json\.dump|open\([^)]*['\"][wa]\+?['\"]).*{t}",
)
LEGIT_TOOLS = re.compile(r"\b(?:project|checks|blur|config)\.py\b")
LEGIT_RUN = re.compile(r"\b(?:python3?|node|ruby)\s+(?:-\S+\s+)*\S*\b(?:project|checks|blur|config)\.py\b")


def segments(cmd):
    return [s for s in re.split(r"&&|\|\||;|\||\n", cmd) if s.strip()]


def hand_edit(cmd, target, extra=None):
    t = re.escape(target) + r"(?![\w.-])"
    if target in cmd and (not extra or extra in cmd) and not LEGIT_RUN.search(cmd):
        if any(re.search(v.replace("{t}", t), cmd) for v in SCRIPT_WRITE):
            return True
    for seg in segments(cmd):
        if target not in seg or (extra and extra not in seg) or LEGIT_TOOLS.search(seg):
            continue
        if any(re.search(v.replace("{t}", t), seg) for v in WRITE_VERBS):
            return True
    return False


def rule_bash_set_checks(payload):
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if re.search(r"\bproject\.py\b[^|;&\n]*\bset\s+checks\b", cmd):
        return "`project.py set checks` is refused: #checks is written only by checks.py / blur.py verify."
    return None


def rule_bash_hand_edit_project(payload):
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if hand_edit(cmd, "project.json"):
        return ("project.json must not be edited by hand (sed/redirect/tee/cp/mv/script): use "
                "project.py set <key> --as <owner>; #checks only by checks.py.")
    return None


def rule_bash_accepted(payload):
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if hand_edit(cmd, "demo.yaml", extra="accepted"):
        return MSG_ACCEPTED
    if re.search(r"\bconfig\.py\b[^|;&\n]*\baccept\b", cmd):
        who = agent_name(payload)
        if who and who != DIRECTOR:
            return ("`config.py accept` records the user's decision: only demo-director runs it, after "
                    "AskUserQuestion. %s must hand the finding to the director." % who)
    return None


BASH_RULES = (rule_bash_set_checks, rule_bash_hand_edit_project, rule_bash_accepted)


def touches_sensitive(payload):
    try:
        blob = json.dumps(payload.get("tool_input") or {}).lower()
    except (TypeError, ValueError):
        return True
    return any(w in blob for w in SENSITIVE_WORDS)


def pre_tool_use(payload):
    """Reason to deny, or None. Privacy-class rules fail closed."""
    if foreign_agent(payload):
        return None
    tool = payload.get("tool_name")
    rules = FILE_RULES if tool in ("Write", "Edit", "MultiEdit") else BASH_RULES if tool == "Bash" else ()
    for rule in rules:
        try:
            why = rule(payload)
        except Exception as e:  # noqa: BLE001 - privacy rules fail closed
            why = ("demo-studio hook error (%s: %s); privacy rules fail closed, so this call is blocked."
                   % (type(e).__name__, e)) if touches_sensitive(payload) else None
        if why:
            return why
    return None


# =========================================================================== SubagentStop
def hook_state_path(sdir):
    return os.path.join(sdir, "hook-state.json")


def load_state(sdir):
    try:
        with open(hook_state_path(sdir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(sdir, state):
    tmp = hook_state_path(sdir) + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, hook_state_path(sdir))


def max_blocks():
    try:
        return max(0, int(os.environ.get("DEMO_HOOK_MAX_BLOCKS", DEFAULT_MAX_BLOCKS)))
    except ValueError:
        return DEFAULT_MAX_BLOCKS


def subagent_stop(payload):
    """Reason to keep the subagent running, or None (allow the stop). Fails open."""
    agent = agent_name(payload)
    if agent not in demo_agents():
        return None
    sys.path.insert(0, SCRIPTS)
    import argparse
    import checks
    import demo
    if agent not in checks.DOD_AGENT_STAGE:
        return None
    demo_dir = demo.find_demo_dir(payload.get("cwd") or os.getcwd())
    if not demo_dir:
        return None
    slug = demo.resolve_slug(demo_dir, argparse.Namespace(slug=None), demo.read_state(demo_dir))
    path = os.path.join(demo_dir, slug, "project.json")
    res, _ = checks.run_dod(argparse.Namespace(stage=agent, project=path, slug=None, ffprobe="ffprobe"))
    sdir = os.path.dirname(path)
    state = load_state(sdir)
    entry = state.get(agent) if isinstance(state.get(agent), dict) else {}
    if res["pass"]:
        if entry:
            state.pop(agent, None)
            save_state(sdir, state)
        return None
    items = [i for i in res["items"] if not i["pass"]]
    why = "; ".join("%s: %s" % (i["id"], i["detail"] or "not done") for i in items)
    blocks = int(entry.get("blocks") or 0)
    if blocks >= max_blocks():
        state[agent] = {"blocks": blocks, "blocked": True, "stage": res["stage"], "reason": why[:500]}
        save_state(sdir, state)
        return None   # loop limit reached: let it stop; demo.py status shows the stage as blocked
    state[agent] = {"blocks": blocks + 1, "blocked": False, "stage": res["stage"], "reason": why[:500]}
    save_state(sdir, state)
    return ("demo-studio: the Definition of Done of stage '%s' is not met (attempt %d of %d): %s. "
            "Fix these in your own outputs, or finish with status blocked and the reason."
            % (res["stage"], blocks + 1, max_blocks() + 1, why))


# =========================================================================== entry
def main(argv=None, stdin=None):
    try:
        payload = json.load(stdin or sys.stdin)
        if not isinstance(payload, dict):
            return 0
    except ValueError:
        return 0   # cannot tell what the call is: fail open
    event = payload.get("hook_event_name") or (argv or sys.argv[1:] or [""])[0]
    why = None
    try:
        if event == "PreToolUse":
            why = pre_tool_use(payload)
        elif event == "SubagentStop":
            why = subagent_stop(payload)
    except Exception:  # noqa: BLE001 - SubagentStop and anything unexpected outside the rules: fail open
        why = None
    if why:
        sys.stderr.write(why + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
