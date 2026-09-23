#!/usr/bin/env python3
"""Launching a child safely, and reading what it was actually given.

Shared by the installer and the bench. It exists because these two once held
separate copies of the same logic, and a fix to one left the other — and the
published plugin — with an ungated shell.
"""

import json
import os
import subprocess

HOME = os.path.expanduser("~")

# What the CLI appends after the role body when the card declares memory.
MEMORY_BLOCK = "# Persistent Agent Memory"

# The seven session-linking variables a child `claude -p` inherits. With them
# the assistant joins the owner's session network, sees every live session and
# can write to them without asking (measured 2026-09-23). Stripped in Python
# rather than with `env -u`, which exists only on POSIX.
LINK_VARS = ("CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
             "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID", "CLAUDE_CODE_CHILD_SESSION",
             "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_ENTRYPOINT")


def isolated_env():
    env = dict(os.environ)
    for v in LINK_VARS:
        env.pop(v, None)
    env["CLAUDE_CODE_HARBOR_KITE"] = "0"
    return env


def launch_argv(prompt, project, disallowed, strict_mcp, budget, extra=None):
    """The general form: a ready denylist, not capability groups.

    Callers that think in capability groups wrap this one — the installer does.
    The budget falls back rather than being omitted: a child launched without
    `--max-budget-usd` bills the owner until it decides to stop.
    """
    argv = ["claude", "-p", prompt, "--add-dir", project,
            "--max-budget-usd", str(budget or "1.00")]
    if disallowed:
        argv.append("--disallowedTools")
        argv.extend(disallowed)
    if strict_mcp:
        argv.append("--strict-mcp-config")
    if extra:
        argv.extend(extra)
    return argv


def run_claude(cwd, argv, timeout=600):
    """Returns the parsed `--output-format json` result, or an error string."""
    try:
        p = subprocess.run(argv, cwd=cwd, env=isolated_env(),
                           capture_output=True, text=True, timeout=timeout)
        return json.loads(p.stdout or "{}"), None
    except Exception as e:
        return None, str(e)


def projects_dir():
    """Per call, not per import: a module that froze this at import time would
    keep reading the real home for the whole test run — and, in a long-lived
    process, would miss a CLAUDE_CONFIG_DIR set after startup."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects")


def find_transcript(session_id):
    """By session id, not by reproducing the directory-slug rule: that rule is
    the harness's to change, the id is not."""
    p = projects_dir()
    if not session_id or not os.path.isdir(p):
        return None
    want = str(session_id) + ".jsonl"
    for d in os.listdir(p):
        cand = os.path.join(p, d, want)
        if os.path.exists(cand):
            return cand
    return None


def system_prompt_parts(path):
    """The `attachment.type == "prompt_snapshot"` payload — what the model was
    really given, as opposed to what the settings say it should have been."""
    parts = None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            a = d.get("attachment")
            if isinstance(a, dict) and a.get("type") == "prompt_snapshot":
                parts = a.get("systemPrompt")
    return parts if isinstance(parts, list) and parts else None
