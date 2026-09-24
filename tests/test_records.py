"""Записи по формату: `formats:` и `records:` карточки → формат в доме, строка
в CLAUDE.md, хук lint-records на PreToolUse.

Хук запускается той самой командой, что записана в правах (как в
test_hooks.py): опечатка в команде роняет тест, а не проходит мимо. Пара
«отказывает без шапки / пропускает правильную / молчит вне records» отличает
сторожа от того, кто отказывает всему подряд.
"""

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402

ROLE = "recorder"
BODY = "Ты ассистент {PROJECT}. Дом: {HOME}.\n"
RECORDS = "docs/dossiers/*.md"
# Роль пишет туда, где лежат её записи: records вне writes установщик отвергает.
CARD = ["access: write-scoped", 'writes: ["docs/dossiers/**"]', "formats: [seed-record]", "records: %s" % RECORDS, "hooks: [lint-records]"]

GOOD = """---
topic: welcome-page
question: Что на странице Welcome и где каждая строка задана в коде
collected: 2026-09-24
commit: c3626e6f
confidence: high
source: отчёт субагента; каждая ссылка перепроверена чтением файла
---
# Welcome

## Вердикт

Порядок: шапка, Start и Recent, Walkthroughs, подвал.

## Открытые вопросы
"""
BARE = "# Welcome\n\nПросто текст без шапки.\n"


def seed_role(sb, card_lines):
    lib = os.path.join(sb.home, ".cckit", "library", ROLE)
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, "card.yaml"), "w", encoding="utf-8") as fh:
        fh.write("name: %s\nsummary: роль для записей\naccess: read-only\n" % ROLE)
        fh.write("".join(l + "\n" for l in card_lines))
    with open(os.path.join(lib, "ROLE.md"), "w", encoding="utf-8") as fh:
        fh.write(BODY)


def install(sb, card_lines=CARD):
    project = sb.project
    home = ck.instance_home(ROLE, project)
    sb.set_reply("готово", transcript_prompt=BODY.replace("{PROJECT}", project)
                 .replace("{HOME}", home).strip())
    seed_role(sb, card_lines)
    rc = ck.cmd_install([ROLE, "--project", project])
    return rc, home


def fire(home, payload):
    cmd = None
    with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
        spec = json.load(fh)["hooks"]
    for g in spec.get("PreToolUse", []):
        for h in g["hooks"]:
            if h["command"].endswith(" lint-records"):
                cmd = h["command"]
    if cmd is None:
        raise AssertionError("в правах нет lint-records на PreToolUse")
    proc = subprocess.run(["bash", "-c", cmd], input=json.dumps(payload),
                          capture_output=True, text=True)
    out = (proc.stdout or "").strip()
    return proc.returncode, (json.loads(out) if out else {})


def decision(home, project, tool, ti):
    rc, d = fire(home, {"hook_event_name": "PreToolUse", "tool_name": tool,
                        "cwd": project, "tool_input": ti})
    h = d.get("hookSpecificOutput") or {}
    return rc, h.get("permissionDecision"), h.get("permissionDecisionReason") or ""


@unittest.skipIf(sys.platform == "win32", "полиглот на windows проверяется отдельно")
class TestFormatsInstall(unittest.TestCase):
    def test_the_format_reaches_the_home_and_claude_md_names_template_and_records(self):
        with Sandbox() as sb:
            _, home = install(sb)
            fdir = os.path.join(home, "formats", "seed-record")
            with open(os.path.join(home, "CLAUDE.md"), encoding="utf-8") as fh:
                md = fh.read()
            with open(os.path.join(ck.hooks_dir(home), "config.json"), encoding="utf-8") as fh:
                cfg = json.load(fh)
            line = [l for l in md.splitlines() if l.startswith("- Записи в")]
            self.assertEqual(
                (sorted(os.listdir(fdir)), len(line),
                 "`%s`" % RECORDS in line[0] if line else None,
                 "`%s`" % os.path.join(fdir, "TEMPLATE.md") in line[0] if line else None,
                 cfg["formats"], cfg["records"]),
                (["README.md", "TEMPLATE.md", "component.yaml", "lint.py"], 1, True, True,
                 ["seed-record"], [RECORDS]), md)

    def test_the_home_cannot_edit_its_own_format(self):
        with Sandbox() as sb:
            _, home = install(sb)
            with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
                deny = json.load(fh)["permissions"]["deny"]
            self.assertIn(ck.abs_rule("Edit", home + "/formats/**"), deny)

    def test_an_unknown_format_stops_the_install_and_lists_the_known_ones(self):
        with Sandbox() as sb:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                install(sb, ["formats: [no-such-format]"])
            self.assertEqual(
                ("no-such-format" in err.getvalue(), "seed-record" in err.getvalue(),
                 os.path.exists(ck.instance_home(ROLE, sb.project))),
                (True, True, False), err.getvalue())

    def test_lint_records_without_records_stops_the_install(self):
        with Sandbox() as sb:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                install(sb, ["formats: [seed-record]", "hooks: [lint-records]"])
            self.assertIn("lint-records", err.getvalue())

    def test_a_format_without_records_still_arrives_with_its_template_line(self):
        with Sandbox() as sb:
            _, home = install(sb, ["formats: [seed-record]"])
            with open(os.path.join(home, "CLAUDE.md"), encoding="utf-8") as fh:
                md = fh.read()
            self.assertEqual(
                (os.path.isfile(os.path.join(home, "formats", "seed-record", "TEMPLATE.md")),
                 "Формат seed-record" in md), (True, True), md)


@unittest.skipIf(sys.platform == "win32", "полиглот на windows проверяется отдельно")
class TestLintRecords(unittest.TestCase):
    def test_refuses_a_bare_record_passes_a_good_one_and_ignores_other_files(self):
        with Sandbox() as sb:
            _, home = install(sb)
            rec = os.path.join(sb.project, "docs", "dossiers", "welcome.md")
            deep = os.path.join(sb.project, "docs", "dossiers", "sub", "x.md")
            bare = decision(home, sb.project, "Write", {"file_path": rec, "content": BARE})
            rel = decision(home, sb.project, "Write",
                           {"file_path": "docs/dossiers/welcome.md", "content": BARE})
            good = decision(home, sb.project, "Write", {"file_path": rec, "content": GOOD})
            other = decision(home, sb.project, "Write",
                             {"file_path": os.path.join(sb.project, "NOTES.md"), "content": BARE})
            nested = decision(home, sb.project, "Write", {"file_path": deep, "content": BARE})
            upper = decision(home, sb.project, "Write", {
                "file_path": os.path.join(sb.project, "Docs", "Dossiers", "W.MD"), "content": BARE})
            self.assertEqual(
                [bare[:2], rel[:2], upper[:2], good, other, nested],
                [(0, "deny"), (0, "deny"), (0, "deny"), (0, None, ""), (0, None, ""), (0, None, "")])
            self.assertTrue("нет шапки" in bare[2] and "TEMPLATE.md" in bare[2]
                            and "НЕ легла" in bare[2], bare[2])

    def test_an_edit_that_breaks_the_record_is_refused_an_old_flaw_does_not_lock(self):
        with Sandbox() as sb:
            _, home = install(sb)
            d = os.path.join(sb.project, "docs", "dossiers")
            os.makedirs(d)
            rec, old = os.path.join(d, "good.md"), os.path.join(d, "old.md")
            for p, text in ((rec, GOOD), (old, BARE)):
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(text)
            breaks = decision(home, sb.project, "Edit", {
                "file_path": rec, "old_string": "## Вердикт", "new_string": "## Контекст"})
            fixes_old = decision(home, sb.project, "Edit", {
                "file_path": old, "old_string": "Просто текст", "new_string": "Другой текст"})
            multi = decision(home, sb.project, "MultiEdit", {
                "file_path": rec, "edits": [
                    {"old_string": "confidence: high", "new_string": "confidence: уверен"}]})
            self.assertEqual([breaks[1], fixes_old[:2], multi[1]],
                             ["deny", (0, None), "deny"])

    def test_a_missing_format_linter_says_so_instead_of_passing_silently(self):
        with Sandbox() as sb:
            _, home = install(sb)
            os.remove(os.path.join(home, "formats", "seed-record", "lint.py"))
            rc, d = fire(home, {"hook_event_name": "PreToolUse", "tool_name": "Write",
                                "cwd": sb.project, "tool_input": {
                                    "file_path": os.path.join(sb.project, "docs", "dossiers", "a.md"),
                                    "content": BARE}})
            self.assertEqual((rc, "lint-records" in d.get("systemMessage", "")), (0, True), d)


# Поддельный CLI для пробы: зовёт PreToolUse-хуки на Write из просьбы и
# честно не пишет файл при отказе — как настоящий.
RECORD_AWARE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys
state = os.environ["CCKIT_FAKE_STATE"]
argv = sys.argv[1:]
with open(os.path.join(state, "calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "cwd": os.getcwd()}) + "\n")
prompt = argv[argv.index("-p") + 1] if "-p" in argv else ""
home = os.getcwd()
with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
    hooks = json.load(fh).get("hooks") or {}
m = re.search(r"файл (\S+HOOKREC-[0-9A-Z]+\S*) с", prompt)
if m:
    path = m.group(1)
    body = {"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": home,
            "tool_input": {"file_path": path, "content": "# x\n"}}
    denied = False
    for g in hooks.get("PreToolUse") or []:
        for h in g.get("hooks") or []:
            p = subprocess.run(h["command"], shell=True, cwd=home, input=json.dumps(body),
                               capture_output=True, text=True)
            try:
                d = json.loads(p.stdout or "{}")
            except Exception:
                d = {}
            denied = denied or (d.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny"
    if not denied:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write("# x\n")
sys.stdout.write(json.dumps({"result": "готово", "session_id": "s1", "total_cost_usd": 0.0}))
'''


@unittest.skipIf(sys.platform == "win32", "полиглот на windows проверяется отдельно")
class TestProbeLintRecords(unittest.TestCase):
    def _home(self, sb):
        home = os.path.join(sb.home, ".cckit", "assistants",
                            ROLE + "@" + os.path.basename(sb.project))
        os.makedirs(home, exist_ok=True)
        card = {"name": ROLE, "summary": "проба", "access": "write-scoped", "writes": ["docs/dossiers/**"],
                "formats": ["seed-record"], "records": RECORDS, "hooks": ["lint-records"]}
        ck.apply_grants(home, ROLE, sb.project, card, set(ck.BASE_CAPS), extra_read=[])
        return home, card

    def _aware(self, sb):
        p = os.path.join(sb.bin, "claude")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(RECORD_AWARE_CLAUDE)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def test_a_working_hook_is_ok_and_the_probe_leaves_the_project_as_it_was(self):
        with Sandbox() as sb:
            self._aware(sb)
            home, card = self._home(sb)
            before = sorted(os.listdir(sb.project))
            state, note = ck.probe_hooks(home, sb.project, card)
            self.assertEqual((state, sorted(os.listdir(sb.project))), ("ок", before), note)

    def test_a_linter_that_never_complains_is_caught_on_the_disk(self):
        with Sandbox() as sb:
            self._aware(sb)
            home, card = self._home(sb)
            with open(os.path.join(home, "formats", "seed-record", "lint.py"), "w") as fh:
                fh.write("def lint(text):\n    return []\n")
            state, note = ck.probe_hooks(home, sb.project, card)
            self.assertEqual((state, os.path.exists(os.path.join(sb.project, "docs"))),
                             ("НЕ РАЗЛИЧИЛ", False), note)

    def test_a_cli_that_writes_nothing_is_not_proven_rather_than_broken(self):
        with Sandbox() as sb:
            home, card = self._home(sb)
            state, note = ck.probe_hooks(home, sb.project, card)
            self.assertEqual(state, "НЕ ДОКАЗАН", note)


if __name__ == "__main__":
    unittest.main()
