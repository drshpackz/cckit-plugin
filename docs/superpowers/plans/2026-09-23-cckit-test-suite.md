# CCKit Assistants — test suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every bug we found by accident today fails a test tomorrow, and the suite runs in seconds without spending a cent or touching the owner's real assistants.

**Architecture:** Four layers, and only the first two run by default. A fake `claude` executable on `PATH` records the argv, environment and working directory it was called with, and can write a transcript on demand — which turns the fence, the isolation and the whole install flow into pure assertions with no model, no network and no spend. Live probes against the real CLI stay opt-in behind an environment variable. `claude plugin eval` covers the one thing a unit test cannot: whether a skill actually triggers.

**Tech Stack:** python3 (3.9.6 floor, stdlib only), `unittest`, a fake `claude` written in python with a `.cmd` shim for Windows, GitHub Actions matrix ubuntu/macos/windows.

**Spec:** `/Users/m1/chiavs-code/docs/superpowers/specs/2026-09-23-cckit-assistants-requirements.md` — sections I (изоляция), K (группы возможностей) and O (ограда проверяется, а не обещается) are what this suite holds in place.

## Global Constraints

- **A test never touches the real `$HOME`.** Every test runs with `HOME` and `CLAUDE_CONFIG_DIR` pointed at a temporary directory. A suite that can delete `~/.cckit/assistants/design-scout@chiavs-code` is a liability, not a safety net.
- **The default suite costs nothing and reaches no network.** Anything that invokes the real `claude` is skipped unless `CCKIT_LIVE=1`. CI never sets it.
- **The default suite finishes in under 30 seconds.** A suite slow enough to skip gets skipped.
- **python3 3.9.6, standard library only.** No pytest, no mock libraries beyond `unittest.mock`, no fixtures framework.
- **No absolute paths from any one machine**, in tests as much as in code. `dev.sh check` already fails the build on `/Users/m1`.
- **Every path assertion must hold on Windows.** `os.path.join`, never `"a/b"`; compare with `os.path.normcase(os.path.normpath(p))`.
- **Test command:** `cd ~/cckit-plugin && python3 -m unittest discover -s tests -v`.

## Review Focus

Five ways a test suite lies, each pinned to the task that owns it.

1. **A test that is green because nothing ran** — the fake `claude` was never invoked and the assertion trivially held. Every test that expects a launch asserts the call was recorded. (Task 1)
2. **A test that escapes into the real home** — one forgotten `HOME` override and the suite rewrites the owner's live instance. The harness fails loudly if `HOME` still points at the real one. (Task 1)
3. **A Windows path that silently matches nothing** — `C:\Users\x` in a permission rule written for a doubled-slash POSIX form fences nothing at all, and nothing warns. (Task 5)
4. **A CI matrix that skips instead of failing** — a missing python or a skipped job reports green. The workflow must fail on a skipped required job. (Task 5)
5. **A live probe running unattended** — the opt-in variable set once in CI bills the account on every push. The guard is asserted, not assumed. (Task 3)

---

### Task 1: The harness — a fake `claude`, and a home that cannot be the real one

**Files:**
- Create: `tests/harness.py`
- Create: `tests/fake_claude.py`
- Modify: `bin/cckit_core.py` (resolve the projects directory at call time, not import time)
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: `cckit_core`.
- Produces, used by every later task:
  - `class Sandbox` — context manager. Attributes: `home` (str), `project` (str), `bin` (str). On enter it sets `HOME`, `USERPROFILE`, `CLAUDE_CONFIG_DIR`, and prepends `bin` to `PATH`; on exit it restores them and removes the tree.
  - `Sandbox.calls() -> list[dict]` — one record per fake invocation: `{"argv": [...], "env": {...}, "cwd": str}`
  - `Sandbox.set_reply(result: str, session_id: str = "s1", transcript_prompt: str = None)` — what the next fake invocation returns, and optionally a transcript it writes
  - `cckit_core.projects_dir() -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_harness.py
import os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
from harness import Sandbox
import cckit_core as core


class TestSandbox(unittest.TestCase):
    def test_home_is_not_the_real_home(self):
        real = os.path.expanduser("~")
        with Sandbox() as sb:
            self.assertNotEqual(os.path.normpath(sb.home), os.path.normpath(real))
            self.assertEqual(os.path.normpath(os.environ["HOME"]),
                             os.path.normpath(sb.home))

    def test_environment_is_restored_on_exit(self):
        before = os.environ.get("HOME")
        with Sandbox():
            pass
        self.assertEqual(os.environ.get("HOME"), before)

    def test_projects_dir_follows_the_sandbox(self):
        # Resolved per call: a module that computed it at import time would
        # keep pointing at the real home for the whole test run.
        with Sandbox() as sb:
            self.assertTrue(core.projects_dir().startswith(sb.home))


class TestFakeClaude(unittest.TestCase):
    def test_a_launch_is_recorded_with_argv_env_and_cwd(self):
        with Sandbox() as sb:
            sb.set_reply("привет")
            res, err = core.run_claude(sb.project,
                                       core.launch_argv("q", sb.project, ["Bash"], True, "0.10",
                                                        extra=["--output-format", "json"]))
            self.assertIsNone(err)
            self.assertEqual(res["result"], "привет")
            calls = sb.calls()
            self.assertEqual(len(calls), 1, "фальшивый claude не вызывался — тест зелёный впустую")
            self.assertIn("--strict-mcp-config", calls[0]["argv"])

    def test_a_test_that_expects_a_call_and_gets_none_fails(self):
        with Sandbox() as sb:
            self.assertEqual(sb.calls(), [])

    def test_fake_writes_a_transcript_when_asked(self):
        with Sandbox() as sb:
            sb.set_reply("ok", session_id="abc", transcript_prompt="ТЕЛО РОЛИ")
            core.run_claude(sb.project, core.launch_argv("q", sb.project, [], True, "0.10",
                                                         extra=["--output-format", "json"]))
            t = core.find_transcript("abc")
            self.assertIsNotNone(t, "стенограмма не найдена по id сессии")
            self.assertEqual(core.system_prompt_parts(t)[0], "ТЕЛО РОЛИ")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd ~/cckit-plugin && python3 -m unittest tests.test_harness -v`
Expected: FAIL — `No module named 'harness'`

- [ ] **Step 3: Write the fake**

```python
#!/usr/bin/env python3
"""A `claude` that answers from a file and records how it was called.

It exists so the fence, the isolation and the install flow can be asserted
without a model, a network or a bill.
"""

import json
import os
import sys


def main():
    state = os.environ["CCKIT_FAKE_STATE"]
    reply = {"result": "", "session_id": "s1", "total_cost_usd": 0.0}
    rp = os.path.join(state, "reply.json")
    if os.path.exists(rp):
        reply.update(json.load(open(rp, encoding="utf-8")))

    with open(os.path.join(state, "calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                             "env": dict(os.environ)}, ensure_ascii=False) + "\n")

    prompt = reply.pop("transcript_prompt", None)
    if prompt:
        d = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR",
                                        os.path.join(os.path.expanduser("~"), ".claude")),
                         "projects", "box")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, reply["session_id"] + ".jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "attachment", "attachment": {
                "type": "prompt_snapshot", "systemPrompt": [prompt]}}) + "\n")

    sys.stdout.write(json.dumps(reply, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write the sandbox**

```python
"""A temporary home, a fake `claude` on PATH, and the guarantee that neither
outlives the test."""

import json
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VARS = ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "PATH", "CCKIT_FAKE_STATE")


class Sandbox(object):
    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in VARS}
        self.root = tempfile.mkdtemp(prefix="cckit-test-")
        self.home = os.path.join(self.root, "home")
        self.project = os.path.join(self.root, "project")
        self.bin = os.path.join(self.root, "bin")
        self.state = os.path.join(self.root, "state")
        for d in (self.home, self.project, self.bin, self.state):
            os.makedirs(d)

        real = os.path.normpath(os.path.expanduser("~"))
        if os.path.normpath(self.home) == real:
            raise AssertionError("песочница совпала с настоящим домом")

        os.environ["HOME"] = self.home
        os.environ["USERPROFILE"] = self.home
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.home, ".claude")
        os.environ["CCKIT_FAKE_STATE"] = self.state
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
        self._install_fake()
        return self

    def _install_fake(self):
        fake = os.path.join(HERE, "fake_claude.py")
        sh = os.path.join(self.bin, "claude")
        with open(sh, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, fake))
        os.chmod(sh, os.stat(sh).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # PATHEXT makes `claude` resolve to claude.cmd on Windows.
        with open(os.path.join(self.bin, "claude.cmd"), "w", encoding="utf-8") as fh:
            fh.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, fake))

    def set_reply(self, result, session_id="s1", transcript_prompt=None, cost=0.0):
        d = {"result": result, "session_id": session_id, "total_cost_usd": cost}
        if transcript_prompt is not None:
            d["transcript_prompt"] = transcript_prompt
        json.dump(d, open(os.path.join(self.state, "reply.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)

    def calls(self):
        p = os.path.join(self.state, "calls.jsonl")
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.root, ignore_errors=True)
        return False
```

- [ ] **Step 5: Make the projects directory resolve per call**

In `bin/cckit_core.py` replace the module-level `PROJECTS` with:

```python
def projects_dir():
    """Per call, not per import: a module that froze this at import time would
    keep reading the real home for the whole test run — and, in a long-lived
    process, would miss a CLAUDE_CONFIG_DIR set after startup."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects")
```

and in `find_transcript` use `p = projects_dir()` in place of `PROJECTS`. Grep for other uses: `rg -n 'PROJECTS' bin/` must come back empty.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd ~/cckit-plugin && python3 -m unittest tests.test_harness -v`
Expected: 6 tests, OK

- [ ] **Step 7: Prove the sandbox really is sealed**

Run:
```bash
cd ~/cckit-plugin && ls ~/.cckit/assistants/ && python3 -m unittest discover -s tests -q && ls ~/.cckit/assistants/
```
Expected: the same listing before and after. A suite that alters it has already failed, whatever the test output said.

- [ ] **Step 8: Commit**

```bash
cd ~/cckit-plugin && git add tests/harness.py tests/fake_claude.py tests/test_harness.py bin/cckit_core.py && \
git commit -m "test: a fake claude and a home that cannot be the real one

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Regression tests for the fence

Every one of these is a hole that was open in shipped code today, found by hand. None has a test.

**Files:**
- Test: `tests/test_fence.py`
- Modify: `bin/cckit_assistant.py` only if a test proves a hole is still open.

**Interfaces:**
- Consumes: `Sandbox` from Task 1; `compile_settings(card, project, home, role, granted=None)`, `CAPS`, `NEVER`, `DANGEROUS` from `cckit_assistant`.
- Produces: nothing new. This task adds tests, and fixes only what they catch.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fence.py
import os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
from harness import Sandbox
import cckit_assistant as ck


def settings(caps=(), granted=None, home="/h", project="/p"):
    card = {"name": "t", "capabilities": list(caps)}
    return ck.compile_settings(card, project, home, "t", granted=granted)


class TestNoToolEscapesTheDenylist(unittest.TestCase):
    def test_every_capability_tool_is_either_granted_or_denied(self):
        s = settings()
        denied = set(s["permissions"]["deny"])
        for group, tools in ck.CAPS.items():
            for tool in tools:
                self.assertTrue(any(tool in d for d in denied),
                                "%s (группа %s) не назван нигде — он разрешён" % (tool, group))

    def test_monitor_is_a_shell_and_is_denied_without_the_shell_group(self):
        # Monitor runs shell commands. It was outside CAPS entirely and so was
        # never denied: an assistant forbidden Bash ran commands through it.
        self.assertIn("Monitor", ck.CAPS["shell"])
        self.assertTrue(any("Monitor" in d for d in settings()["permissions"]["deny"]))

    def test_never_tools_are_denied_even_when_everything_is_granted(self):
        s = settings(caps=ck.CAPS.keys(), granted=list(ck.CAPS.keys()))
        for tool in ck.NEVER:
            self.assertTrue(any(tool in d for d in s["permissions"]["deny"]), tool)


class TestPathRules(unittest.TestCase):
    def test_no_bare_read_or_edit_in_allow(self):
        # A bare "Read" grants the whole filesystem — proved by reading
        # /etc/hosts from an assistant that was supposed to see one project.
        for rule in settings()["permissions"]["allow"]:
            self.assertNotIn(rule, ("Read", "Edit", "Write", "NotebookEdit"),
                             "правило без пути даёт всю файловую систему")

    def test_absolute_path_rules_use_the_doubled_slash_form(self):
        s = settings(home="/h", project="/p")
        for rule in s["permissions"]["allow"]:
            if "(" not in rule:
                continue
            arg = rule.split("(", 1)[1].rstrip(")")
            if arg.startswith("/") and not arg.startswith("//"):
                self.fail("%s: одинарный слэш не совпадает ни с чем — ограда мнимая" % rule)


class TestGrant(unittest.TestCase):
    def test_granting_shell_actually_removes_the_bash_denial(self):
        # --grant shell reported success while compile_settings never saw the
        # grant and denied Bash anyway.
        s = settings(caps=["shell"], granted=["shell"])
        self.assertFalse(any(d == "Bash" or d.startswith("Bash(") for d in
                             s["permissions"]["deny"]))

    def test_a_dangerous_group_is_denied_when_not_granted(self):
        s = settings(caps=["shell"], granted=None)
        self.assertTrue(any("Bash" in d for d in s["permissions"]["deny"]))

    def test_every_dangerous_group_exists_in_caps(self):
        for g in ck.DANGEROUS:
            self.assertIn(g, ck.CAPS, "опасная группа %s не описана в CAPS" % g)


class TestTrust(unittest.TestCase):
    def test_install_marks_both_the_home_and_the_project_as_trusted(self):
        # An untrusted workspace silently voids every allow rule: the fence
        # compiles, is written, and does nothing.
        with Sandbox() as sb:
            sb.set_reply("ok", transcript_prompt="ROLE")
            ck.write_trust(sb.home)
            ck.write_trust(sb.project)
            cfg = os.path.join(sb.home, ".claude.json")
            self.assertTrue(os.path.exists(cfg))
            import json
            d = json.load(open(cfg, encoding="utf-8"))
            self.assertTrue(any(v.get("hasTrustDialogAccepted")
                                for v in d.get("projects", {}).values()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to see which holes are still open**

Run: `cd ~/cckit-plugin && python3 -m unittest tests.test_fence -v`
Expected: `test_install_marks_both_the_home_and_the_project_as_trusted` fails with `has no attribute 'write_trust'` — the trust write is currently inline in the install command, not a callable unit. Others should pass; any that does not is a live hole and Step 3 closes it.

- [ ] **Step 3: Extract `write_trust` and fix anything else the tests caught**

In `bin/cckit_assistant.py`, lift the inline trust write into:

```python
def write_trust(path):
    """An untrusted workspace voids every allow rule, silently: the fence
    compiles, is written, and permits nothing — which reads exactly like a
    working fence until something is denied that should not be."""
    cfg = os.path.join(os.path.expanduser("~"), ".claude.json")
    d = {}
    if os.path.exists(cfg):
        try:
            d = json.load(open(cfg, encoding="utf-8"))
        except Exception:
            d = {}
    d.setdefault("projects", {}).setdefault(path, {})["hasTrustDialogAccepted"] = True
    with open(cfg, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1)
```

and call it from the install path for both the instance home and the project.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/cckit-plugin && python3 -m unittest tests.test_fence -v`
Expected: 9 tests, OK

- [ ] **Step 5: Commit**

```bash
cd ~/cckit-plugin && git add tests/test_fence.py bin/cckit_assistant.py && \
git commit -m "test: pin every fence hole found by hand today

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The launcher contract, and the guard on live runs

**Files:**
- Test: `tests/test_launch_contract.py`
- Create: `tests/live/__init__.py`, `tests/live/test_live_probe.py`

**Interfaces:**
- Consumes: `Sandbox`, `cckit_core.launch_argv`, `cckit_core.isolated_env`.
- Produces: `LIVE = os.environ.get("CCKIT_LIVE") == "1"` in `tests/live/__init__.py`, used by every live test's `@unittest.skipUnless`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_launch_contract.py
import os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
from harness import Sandbox
import cckit_core as core


class TestIsolationReachesTheChild(unittest.TestCase):
    def test_no_link_var_survives_into_the_childs_environment(self):
        # Asserted on the environment the child actually saw, not on the dict
        # we built: the gap between those two is where this kind of bug lives.
        with Sandbox() as sb:
            for v in core.LINK_VARS:
                os.environ[v] = "leak"
            try:
                sb.set_reply("ok")
                core.run_claude(sb.project, core.launch_argv("q", sb.project, [], True, "0.10",
                                                             extra=["--output-format", "json"]))
                calls = sb.calls()
                self.assertEqual(len(calls), 1)
                for v in core.LINK_VARS:
                    self.assertNotIn(v, calls[0]["env"], v + " дошёл до ребёнка")
                self.assertEqual(calls[0]["env"].get("CLAUDE_CODE_HARBOR_KITE"), "0")
            finally:
                for v in core.LINK_VARS:
                    os.environ.pop(v, None)

    def test_every_launch_carries_a_budget_and_strict_mcp(self):
        with Sandbox() as sb:
            sb.set_reply("ok")
            core.run_claude(sb.project, core.launch_argv("q", sb.project, ["Bash"], True, "0.25",
                                                         extra=["--output-format", "json"]))
            argv = sb.calls()[0]["argv"]
            self.assertIn("--strict-mcp-config", argv)
            self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.25")

    def test_a_timeout_is_an_error_not_a_silent_empty_result(self):
        with Sandbox() as sb:
            res, err = core.run_claude(sb.project, [sys.executable, "-c",
                                                    "import time; time.sleep(5)"], timeout=1)
            self.assertIsNone(res)
            self.assertIsNotNone(err)


class TestLiveGuard(unittest.TestCase):
    def test_live_tests_are_off_unless_explicitly_enabled(self):
        # The variable set once in CI bills the account on every push.
        sys.path.insert(0, os.path.dirname(__file__))
        import live
        self.assertEqual(live.LIVE, os.environ.get("CCKIT_LIVE") == "1")

    def test_ci_workflow_does_not_set_the_live_variable(self):
        wf = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "test.yml")
        self.assertNotIn("CCKIT_LIVE", open(wf, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to make sure they fail**

Run: `cd ~/cckit-plugin && python3 -m unittest tests.test_launch_contract -v`
Expected: FAIL — `No module named 'live'` and the workflow file does not exist yet (Task 5 creates it; this test is why it must stay clean).

- [ ] **Step 3: Write the live package**

```python
# tests/live/__init__.py
"""Tests here invoke the real `claude`. They cost money and reach the network,
so they run only when asked for by name."""

import os

LIVE = os.environ.get("CCKIT_LIVE") == "1"
```

```python
# tests/live/test_live_probe.py
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))
from . import LIVE
import cckit_core as core


@unittest.skipUnless(LIVE, "живые прогоны стоят денег: CCKIT_LIVE=1")
class TestRealCli(unittest.TestCase):
    def test_the_cli_answers_and_reports_a_session_id(self):
        res, err = core.run_claude(os.path.expanduser("~"),
                                   core.launch_argv("Ответь одним словом: готово", os.getcwd(),
                                                    ["Bash", "Write", "Edit"], True, "0.05",
                                                    extra=["--output-format", "json"]),
                                   timeout=120)
        self.assertIsNone(err)
        self.assertTrue(res.get("session_id"))

    def test_a_prompt_we_supply_is_visible_in_the_transcript(self):
        # The one claim no fake can support: that the harness really delivers
        # the body we wrote.
        res, _ = core.run_claude(os.getcwd(),
                                 core.launch_argv("скажи ок", os.getcwd(), [], True, "0.05",
                                                  extra=["--output-format", "json"]),
                                 timeout=120)
        t = core.find_transcript(res["session_id"])
        self.assertIsNotNone(t)
        self.assertTrue(core.system_prompt_parts(t))
```

Create the workflow placeholder now so the guard test has something to read; Task 5 fills it in:

```bash
mkdir -p ~/cckit-plugin/.github/workflows && \
printf 'name: tests\non: [push, pull_request]\njobs: {}\n' > ~/cckit-plugin/.github/workflows/test.yml
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/cckit-plugin && python3 -m unittest discover -s tests -v`
Expected: all pass; the two live tests report `skipped 'живые прогоны стоят денег: CCKIT_LIVE=1'`.

- [ ] **Step 5: Run the live pair once, by hand**

Run: `cd ~/cckit-plugin && CCKIT_LIVE=1 python3 -m unittest tests.live.test_live_probe -v`
Expected: 2 tests OK, a few cents. If `test_a_prompt_we_supply_is_visible_in_the_transcript` fails, the transcript format changed under us and every prompt probe in the product is now blind — that is precisely what this test is for.

- [ ] **Step 6: Commit**

```bash
cd ~/cckit-plugin && git add tests/test_launch_contract.py tests/live .github/workflows/test.yml && \
git commit -m "test: assert isolation on the environment the child saw, and keep live runs opt-in

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The install flow end to end

**Files:**
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: `Sandbox`; `cckit_assistant.main(argv)`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_install.py
import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
from harness import Sandbox
import cckit_assistant as ck

PLUGIN = os.path.join(os.path.dirname(__file__), "..")


def install(sb, project, extra=()):
    sb.set_reply("готово", transcript_prompt=open(
        os.path.join(PLUGIN, "assistants", "design-scout", "ROLE.md"),
        encoding="utf-8").read().strip())
    return ck.main(["install", "design-scout", "--project", project] + list(extra))


class TestInstall(unittest.TestCase):
    def test_install_creates_the_instance_with_its_four_files(self):
        with Sandbox() as sb:
            self.assertEqual(install(sb, sb.project), 0)
            home = ck.instance_home("design-scout", sb.project)
            for f in (".claude/settings.json", ".claude/agents/design-scout.md",
                      "CLAUDE.md", "LEARNED.md", "instance.json"):
                self.assertTrue(os.path.exists(os.path.join(home, *f.split("/"))), f)

    def test_two_projects_with_the_same_basename_get_different_homes(self):
        # Both ~/work/editor and ~/old/editor installed into
        # design-scout@editor, and the second overwrote the first's memory.
        with Sandbox() as sb:
            a = os.path.join(sb.root, "work", "editor")
            b = os.path.join(sb.root, "old", "editor")
            os.makedirs(a); os.makedirs(b)
            self.assertNotEqual(ck.instance_home("design-scout", a),
                                ck.instance_home("design-scout", b))

    def test_display_name_comes_from_the_directory_not_the_card(self):
        with Sandbox() as sb:
            install(sb, sb.project)
            home = ck.instance_home("design-scout", sb.project)
            self.assertEqual(ck.display_name(home), os.path.basename(home))

    def test_reinstall_does_not_destroy_the_learned_file(self):
        with Sandbox() as sb:
            install(sb, sb.project)
            home = ck.instance_home("design-scout", sb.project)
            p = os.path.join(home, "LEARNED.md")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("## Запись\n**измерено** важное\n")
            install(sb, sb.project, ["--force"])
            self.assertIn("важное", open(p, encoding="utf-8").read())


class TestGrantRevoke(unittest.TestCase):
    def test_grant_then_revoke_returns_the_settings_to_the_original(self):
        with Sandbox() as sb:
            install(sb, sb.project)
            home = ck.instance_home("design-scout", sb.project)
            sp = os.path.join(home, ".claude", "settings.json")
            before = open(sp, encoding="utf-8").read()
            ck.main(["grant", "design-scout", "--project", sb.project, "shell"])
            self.assertNotEqual(open(sp, encoding="utf-8").read(), before)
            ck.main(["revoke", "design-scout", "--project", sb.project, "shell"])
            self.assertEqual(json.loads(open(sp, encoding="utf-8").read()),
                             json.loads(before))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and fix what they catch**

Run: `cd ~/cckit-plugin && python3 -m unittest tests.test_install -v`
Expected: `test_reinstall_does_not_destroy_the_learned_file` is the one most likely to fail — `--force` currently rewrites the instance wholesale. If it does, change the install path to skip `LEARNED.md` and `memory/` when they already carry content, exactly as it already skips them on a non-forced reinstall. A month of accumulated notes lost to a reinstall is the worst failure this product has.

- [ ] **Step 3: Run the tests to verify they pass**

Run: `cd ~/cckit-plugin && python3 -m unittest tests.test_install -v`
Expected: 5 tests, OK

- [ ] **Step 4: Commit**

```bash
cd ~/cckit-plugin && git add tests/test_install.py bin/cckit_assistant.py && \
git commit -m "test: the whole install flow against a fake CLI, memory survives --force

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Cross-platform — the hook polyglot, Windows paths, and a matrix that cannot skip

**Files:**
- Test: `tests/test_portable.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes: `Sandbox`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_portable.py
import os, subprocess, sys, unittest

PLUGIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HOOKS = os.path.join(PLUGIN, "hooks")


class TestHookShim(unittest.TestCase):
    def test_no_hook_script_name_contains_dot_sh(self):
        # Windows prepends `bash` to anything whose name contains .sh, and then
        # fails when bash is absent. Extensionless names sidestep it.
        for f in os.listdir(HOOKS):
            self.assertNotIn(".sh", f, f)

    def test_the_polyglot_starts_with_the_bash_swallow(self):
        first = open(os.path.join(HOOKS, "run-hook.cmd"), encoding="utf-8").read().splitlines()[0]
        self.assertTrue(first.startswith(": <<"), "bash съест батник только с этой строкой")

    @unittest.skipIf(sys.platform == "win32", "posix half")
    def test_the_hook_emits_valid_json_on_posix(self):
        import json
        p = subprocess.run(["sh", os.path.join(HOOKS, "session-start")],
                           input="{}", capture_output=True, text=True)
        d = json.loads(p.stdout)
        self.assertIn("hookSpecificOutput", d)

    def test_the_hook_is_silent_when_there_is_no_bash(self):
        # A machine without bash must get no hook, not a stack trace on every
        # session start.
        env = dict(os.environ, PATH="")
        p = subprocess.run([os.path.join(HOOKS, "run-hook.cmd")], input="{}",
                           capture_output=True, text=True, env=env, shell=True)
        self.assertEqual(p.returncode, 0, p.stderr)


class TestPaths(unittest.TestCase):
    def test_no_hardcoded_posix_separators_in_permission_rules(self):
        sys.path.insert(0, os.path.join(PLUGIN, "bin"))
        import cckit_assistant as ck
        s = ck.compile_settings({"name": "t", "capabilities": []},
                                os.path.join("C:", os.sep, "p"),
                                os.path.join("C:", os.sep, "h"), "t")
        for rule in s["permissions"]["allow"]:
            if "(" not in rule:
                continue
            arg = rule.split("(", 1)[1].rstrip(")")
            self.assertNotIn("\\", arg,
                             "обратный слэш в правиле не совпадёт ни с чем: " + rule)

    def test_no_absolute_developer_paths_anywhere_in_the_plugin(self):
        bad = subprocess.run(["git", "grep", "-l", "/Users/m1"], cwd=PLUGIN,
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(bad, "", "пути с одной машины: " + bad)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and fix what they catch**

Run: `cd ~/cckit-plugin && python3 -m unittest tests.test_portable -v`
Expected: `test_no_hardcoded_posix_separators_in_permission_rules` is the likely failure — rules are built with `"%s/**"` formatting. Fix by normalising every path argument to forward slashes before it goes into a rule:

```python
def rule_path(p):
    """Permission rules are matched as posix paths on every platform; a rule
    carrying Windows separators fences nothing and says nothing."""
    return "//" + os.path.abspath(p).replace("\\", "/").lstrip("/")
```

and use `rule_path()` everywhere a path enters `allow`/`deny`/`ask`.

- [ ] **Step 3: Write the CI matrix**

```yaml
name: tests
on: [push, pull_request]

jobs:
  suite:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.9'
      - name: Run the suite
        shell: bash
        run: |
          set -euo pipefail
          python -m unittest discover -s tests -v 2>&1 | tee out.txt
          # A run where nothing ran reports success. Require tests to exist.
          grep -Eq 'Ran [1-9][0-9]* tests' out.txt
      - name: No live runs in CI
        shell: bash
        run: test -z "${CCKIT_LIVE:-}"

  required:
    needs: suite
    if: always()
    runs-on: ubuntu-latest
    steps:
      # A skipped or cancelled matrix job otherwise reports green.
      - run: |
          echo "${{ needs.suite.result }}"
          test "${{ needs.suite.result }}" = "success"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/cckit-plugin && python3 -m unittest discover -s tests -v`
Expected: everything passes, live tests skipped.

- [ ] **Step 5: Verify the matrix on a real push**

Run:
```bash
cd ~/cckit-plugin && git add .github/workflows/test.yml tests/test_portable.py bin/cckit_assistant.py && \
git commit -m "test: portability — no .sh hook names, posix rule paths, a matrix that cannot skip

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>" && git push && \
sleep 45 && gh run list --limit 1
```
Expected: three `suite` jobs and one `required`. **Windows is expected to surface something** — it is the platform nothing here has ever run on. Fix what it reports before moving on; a red Windows job is the plan working.

---

### Task 6: Does the skill actually trigger

Unit tests prove the code. They cannot prove that a person typing "мне нужен помощник для дизайна" reaches `create-agent` — and a skill that never fires is indistinguishable from one that does not exist.

**Files:**
- Create: `evals/cckit.eval.json`
- Modify: `dev.sh` (`check` runs the suite; new `eval` subcommand)
- Test: the eval itself is the test.

**Interfaces:**
- Consumes: the installed plugin.
- Produces: `./dev.sh test`, and `check` gaining the suite as a gate.

- [ ] **Step 1: Write the eval suite**

```json
{
  "name": "cckit",
  "cases": [
    {
      "prompt": "Мне нужен постоянный помощник, который собирает сведения о кодовой базе, пока я работаю.",
      "expect": { "skill": "cckit:create-agent" }
    },
    {
      "prompt": "Какие ассистенты у меня уже стоят в этом проекте?",
      "expect": { "skill": "cckit:list-agents" }
    },
    {
      "prompt": "Есть ли готовая роль для ревью кода, которую можно поставить?",
      "expect": { "skill": "cckit:find-agent" }
    },
    {
      "prompt": "Перепиши этот питоновский скрипт, чтобы он читал JSON.",
      "expect": { "skill": null }
    }
  ]
}
```

The fourth case is the one that matters: a skill whose description triggers on everything is worse than one that triggers on nothing.

- [ ] **Step 2: Run it**

Run: `cd ~/cckit-plugin && claude plugin eval evals/cckit.eval.json`
Expected: 4/4. On a miss, edit the offending `SKILL.md` description — only the "Use when" triggering conditions, never the body — and rerun. Do not widen a description to catch case 4; narrow the one that over-fired.

- [ ] **Step 3: Wire the suite into `dev.sh`**

Add to `dev.sh`:

```bash
cmd_test() {
  say "юнит-тесты"
  ( cd "$ROOT" && python3 -m unittest discover -s tests -q ) || die "тесты не прошли"
  ok "тесты"
}

cmd_eval() {
  say "срабатывание скиллов"
  claude plugin eval "$ROOT/evals/cckit.eval.json" || die "скиллы не срабатывают"
  ok "скиллы"
}
```

and call `cmd_test` from `cmd_check` before the manifest gates, so a broken suite stops a publish. Extend the usage line to `check | test | eval | publish [msg] | reinstall [source] | all`, and make `all` run `check → test → publish → reinstall`.

- [ ] **Step 4: Run the whole gate**

Run: `cd ~/cckit-plugin && ./dev.sh check && ./dev.sh eval`
Expected: every gate green, `Ran N tests … OK`, 4/4 on the eval.

- [ ] **Step 5: Commit and publish**

```bash
cd ~/cckit-plugin && git add evals dev.sh && \
git commit -m "test: an eval for skill triggering, and dev.sh check gates on the suite

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>" && ./dev.sh publish "test suite"
```

---

## Self-review against the spec

**Spec coverage.** Section O (ограда проверяется, а не обещается) is Task 2 plus the live probe in Task 3. Section I (изоляция) is Task 3, asserted on the child's own environment rather than on the dict we construct — the distinction that matters. Section K (группы возможностей) is `test_every_capability_tool_is_either_granted_or_denied`, which is the general form of the `Monitor` hole rather than a patch for that one tool. Cross-platform, the requirement the user stated in their own words ("плагин должен работать на linux, macos, windows"), is Task 5. **Not covered:** the bench from the 0.3 plan brings its own tests; nothing here duplicates them.

**Placeholders.** None: every step carries the file, the code and the expected output, including the two steps whose expected output is a failure.

**Type consistency.** `Sandbox` exposes `home`/`project`/`bin`/`root`/`calls()`/`set_reply()` and every later task uses exactly those; `projects_dir()` is defined in Task 1 and relied on in Tasks 1 and 3; `rule_path()` (Task 5) and `write_trust()` (Task 2) are each defined where first needed.

**Review Focus coverage.** (1) green-because-nothing-ran → `test_a_launch_is_recorded_with_argv_env_and_cwd` asserts the call count, and the CI step greps for `Ran N tests`; (2) escaping into the real home → `test_home_is_not_the_real_home`, the `AssertionError` inside `Sandbox.__enter__`, and the before/after listing in Task 1 step 7; (3) Windows paths → `test_no_hardcoded_posix_separators_in_permission_rules`; (4) a matrix that skips → the `required` job; (5) a live probe in CI → `test_ci_workflow_does_not_set_the_live_variable` and the workflow's own `test -z`.

**One honest gap.** Nothing here tests the two bug classes that bit hardest today, because both were in shell scripts now deleted: `«$VAR»` under `set -u`, and `open(f,"w")` truncating before the read. The second is now impossible in the Python — every write reads first — but nothing enforces it. If a shell script comes back, it needs `shellcheck` in the matrix; note it and move on rather than pretending a python suite covers it.
