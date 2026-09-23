# -*- coding: utf-8 -*-
"""Переносимость: хуки, правила прав и матрица CI.

Всё здесь держит одно обещание владельца — плагин работает на linux, macos и
windows. Сегодня он не запускался нигде, кроме одного макбука, и ни один тест
этого не заметил.

Настоящей windows у автора этих тестов нет. Поэтому тесты, где можно, проверяют
ПОВЕДЕНИЕ переносимой части на posix (полиглот-хук исполняется, шлюз матрицы
исполняется), а не только наличие нужных строк в файле.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(PLUGIN, "hooks")
WORKFLOW = os.path.join(PLUGIN, ".github", "workflows", "test.yml")


def workflow_text():
    with open(WORKFLOW, encoding="utf-8") as fh:
        return fh.read()


def job_lines(name):
    """Строки одной работы workflow: от `  <имя>:` до следующего ключа того же
    отступа. Разбор руками потому, что PyYAML в этом репозитории запрещён."""
    out, inside = [], False
    for line in workflow_text().splitlines():
        if re.match(r"^  %s:\s*$" % re.escape(name), line):
            inside = True
            continue
        if inside:
            if line.strip() and not line.startswith("    "):
                break
            out.append(line)
    return out


def run_blocks(lines):
    """Каждый блок `run: |`, приведённый к нулевому отступу — то, что на самом
    деле исполнит раннер."""
    blocks, buf, indent = [], None, 0
    for line in lines:
        if buf is not None:
            if not line.strip() or line.startswith(" " * indent):
                buf.append(line[indent:])
                continue
            blocks.append("\n".join(buf).strip("\n"))
            buf = None
        m = re.match(r"^(\s+)run:\s*\|\s*$", line)
        if m:
            indent = len(m.group(1)) + 2
            buf = []
    if buf is not None:
        blocks.append("\n".join(buf).strip("\n"))
    return blocks


def batch_half():
    """Часть run-hook.cmd, которую исполняет cmd.exe: от @echo off до CMDBLOCK."""
    with open(os.path.join(HOOKS, "run-hook.cmd"), encoding="utf-8") as fh:
        return fh.read().split("CMDBLOCK")[1]


class TestHookNames(unittest.TestCase):
    def test_no_hook_script_name_contains_dot_sh(self):
        # Windows-автоопределение Claude Code дописывает "bash" к любой команде,
        # в которой есть ".sh", и падает там, где bash нет. Имена без расширения
        # обходят это.
        names = sorted(f for f in os.listdir(HOOKS) if not f.startswith("."))
        self.assertTrue(names, "каталог хуков пуст — проверять нечего")
        for f in names:
            self.assertNotIn(".sh", f, f)

    def test_every_hook_command_in_hooks_json_goes_through_the_polyglot(self):
        # Хук, позванный напрямую, минует батник и на windows не запустится.
        with open(os.path.join(HOOKS, "hooks.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        cmds = [h["command"] for group in cfg["hooks"].values()
                for entry in group for h in entry["hooks"]
                if h.get("type") == "command"]
        self.assertTrue(cmds, "в hooks.json не нашлось ни одной команды")
        for c in cmds:
            self.assertIn("run-hook.cmd", c, c)


class TestPolyglot(unittest.TestCase):
    def test_the_polyglot_starts_with_the_bash_swallow(self):
        with open(os.path.join(HOOKS, "run-hook.cmd"), encoding="utf-8") as fh:
            first = fh.read().splitlines()[0]
        self.assertTrue(first.startswith(": <<"),
                        "bash съест батник только с этой строкой, а не с %r" % first)

    @unittest.skipIf(sys.platform == "win32", "posix-половина полиглота")
    def test_the_hook_emits_valid_json_through_the_polyglot(self):
        # Не `bash hooks/session-start`, как в dev.sh, а именно через батник:
        # проверяется, что posix-половина полиглота жива, а не только хук.
        p = subprocess.run(["sh", os.path.join(HOOKS, "run-hook.cmd"), "session-start"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        d = json.loads(p.stdout)
        self.assertTrue(d["hookSpecificOutput"]["additionalContext"].strip())
        self.assertTrue(d["additional_context"].strip())

    def test_the_batch_half_exits_quietly_when_there_is_no_bash(self):
        # На машине без bash хук обязан промолчать, а не ронять стек на каждом
        # старте сессии. Настоящей windows тут нет, поэтому утверждается форма
        # последней ветки: выход нулём и ни звука после проверки `where bash`.
        tail = batch_half().split("where bash", 1)
        self.assertEqual(len(tail), 2, "в батнике нет проверки `where bash`")
        after = tail[1]
        meaningful = [l.strip() for l in after.splitlines()
                      if l.strip() and not l.strip().upper().startswith("REM")]
        self.assertEqual(meaningful[-1], "exit /b 0",
                         "последняя ветка обязана выходить нулём: %r" % meaningful[-1])
        no_bash = after.split(")", 1)[-1]
        self.assertNotIn("echo", no_bash.lower(),
                         "ветка «bash нет» шумит в консоль вместо молчания")

    @unittest.skipUnless(sys.platform == "win32", "только на настоящей windows")
    def test_the_batch_half_really_is_silent_without_bash(self):
        env = dict(os.environ, PATH=os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                                 "System32"))
        p = subprocess.run([os.path.join(HOOKS, "run-hook.cmd"), "session-start"],
                           input="{}", capture_output=True, text=True, env=env)
        self.assertEqual((p.returncode, p.stderr.strip()), (0, ""))


class TestPermissionRulesArePosix(unittest.TestCase):
    """Правило прав сопоставляется как posix-путь на любой платформе."""

    @staticmethod
    def windows_rules():
        sys.path.insert(0, os.path.join(PLUGIN, "bin"))
        import cckit_assistant as ck
        s = ck.compile_settings({"name": "t", "capabilities": []},
                                r"C:\Users\x\p", r"C:\Users\x\h", "t")
        return s["permissions"]["allow"] + s["permissions"]["deny"]

    def test_windows_paths_reach_the_rules_at_all(self):
        # Страховка для теста ниже: без неё @expectedFailure зеленел бы и от
        # опечатки в имени функции.
        rules = self.windows_rules()
        self.assertTrue(any("Users" in r for r in rules),
                        "путь вообще не доехал до правил: %r" % rules)

    @unittest.expectedFailure
    def test_no_backslash_survives_into_a_permission_rule(self):
        # ИЗВЕСТНАЯ ДЫРА, не мой файл: bin/cckit_assistant.abs_rule клеит
        # "//" + path и не трогает разделители, так что на windows выходит
        # Read(//C:\Users\x\p/**) — такое правило не совпадает ни с чем, и
        # ограда молча ничего не огораживает.
        # Декоратор снимается ТЕМ ЖЕ коммитом, что чинит abs_rule: после
        # починки unittest объявит unexpected success и набор станет красным.
        for rule in self.windows_rules():
            if "(" not in rule:
                continue
            arg = rule.split("(", 1)[1].rstrip(")")
            self.assertNotIn("\\", arg,
                             "обратный слэш в правиле не совпадёт ни с чем: " + rule)


class TestNoSingleMachinePaths(unittest.TestCase):
    """Поставляемое = то, что лежит в репозитории.

    Список берётся у git, а не обходом каталога: обход спотыкается о местные
    артефакты прогонов (evals/results/), которых нет ни у кого, кроме этой
    машины, и тест становился бы красным у всех остальных по другой причине.
    """

    # docs/ и .github/ исключены так же, как в dev.sh: планы законно цитируют
    # команды, которые правда выполнялись. LEARNED.md — такой же журнал.
    SKIP_DIRS = ("docs/", ".github/")
    SKIP_FILES = ("dev.sh", "LEARNED.md", "tests/" + os.path.basename(__file__))

    def shipped_files(self):
        p = subprocess.run(["git", "ls-files", "-z"], cwd=PLUGIN,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, "git ls-files не отработал: " + p.stderr)
        rel = [f for f in p.stdout.split("\0") if f]
        self.assertGreater(len(rel), 20, "git отдал %d файлов — список пуст" % len(rel))
        return [f for f in rel
                if not f.startswith(self.SKIP_DIRS) and f not in self.SKIP_FILES]

    def test_no_absolute_developer_paths_anywhere_in_the_plugin(self):
        # Игла собрана из кусков, чтобы файл теста не был сам себе находкой.
        needles = ["/" + "Users" + "/m1"]
        real = os.path.expanduser("~")
        if re.match(r"^[/\\](Users|home)[/\\][^/\\]+$", real):
            needles.append(real)
        bad, seen = [], 0
        for rel in self.shipped_files():
            try:
                with open(os.path.join(PLUGIN, rel), encoding="utf-8") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            seen += 1
            if any(n in text for n in needles):
                bad.append(rel)
        self.assertGreater(seen, 20, "прочитано %d файлов — проверка пустая" % seen)
        self.assertEqual(bad, [], "пути с одной машины: %s" % bad)


class TestCIMatrix(unittest.TestCase):
    def test_the_matrix_covers_three_platforms_on_the_python_floor(self):
        lines = job_lines("suite")
        self.assertTrue(lines, "работы suite нет в workflow")
        text = "\n".join(lines)
        for token in ("ubuntu-latest", "macos-latest", "windows-latest", "'3.9'"):
            self.assertIn(token, text, token)

    def test_every_needed_job_exists(self):
        # Текстовые проверки ниже зеленели бы и на workflow, где работа
        # переименована: `needs: suite` при отсутствующей suite — это
        # сломанный запуск, а не пройденный шлюз.
        text = workflow_text()
        jobs = set(re.findall(r"^  (\w[\w-]*):\s*$", text, re.M))
        self.assertTrue({"suite", "required"} <= jobs, jobs)
        for need in re.findall(r"^\s+needs:\s*(\S+)\s*$", text, re.M):
            self.assertIn(need, jobs, "needs: %s — такой работы нет" % need)

    def test_the_suite_step_refuses_a_run_where_nothing_ran(self):
        # Матрица врёт зелёным, если тесты не собрались: "Ran 0 tests" — это
        # провал в зелёной шляпе.
        m = re.search(r"grep -Eq '([^']+)'", workflow_text())
        self.assertIsNotNone(m, "в workflow нет проверки «тесты вообще шли»")
        pat = m.group(1)
        verdicts = {s: bool(re.search(pat, s)) for s in
                    ("Ran 106 tests in 2.2s", "Ran 1 test in 0.1s",
                     "Ran 0 tests in 0.000s", "")}
        self.assertEqual(verdicts, {"Ran 106 tests in 2.2s": True,
                                    "Ran 1 test in 0.1s": True,
                                    "Ran 0 tests in 0.000s": False,
                                    "": False})

    def test_the_suite_step_does_not_lose_failure_in_the_pipe(self):
        # `python -m unittest | tee` без pipefail отдаёт код tee, то есть 0
        # всегда: красный набор стал бы зелёным шагом.
        piped = [b for b in run_blocks(job_lines("suite")) if "tee" in b]
        self.assertTrue(piped, "шаг прогона не найден")
        for b in piped:
            self.assertIn("pipefail", b, b)

    def test_the_gate_runs_even_when_the_matrix_did_not(self):
        text = "\n".join(job_lines("required"))
        self.assertIn("if: always()", text,
                      "без always() шлюз просто не запустится и не поймает пропуск")
        self.assertIn("needs.suite.result", text)

    @unittest.skipUnless(shutil.which("bash"), "нужен bash")
    def test_the_gate_fails_on_skipped_and_cancelled_not_only_on_failure(self):
        # Пропущенная и отменённая работа матрицы — это непроверенная
        # платформа. Шлюз исполняется по-настоящему, с подстановкой каждого
        # значения needs.<job>.result.
        blocks = [b for b in run_blocks(job_lines("required"))
                  if "needs.suite.result" in b]
        self.assertEqual(len(blocks), 1, "шлюз не найден или их несколько")
        script = blocks[0]
        got = {}
        for result in ("success", "failure", "cancelled", "skipped"):
            body = script.replace("${{ needs.suite.result }}", result)
            self.assertNotIn("${{", body, "подстановка не сработала")
            got[result] = subprocess.run(["bash", "-c", body],
                                         capture_output=True, text=True).returncode == 0
        self.assertEqual(got, {"success": True, "failure": False,
                               "cancelled": False, "skipped": False})


if __name__ == "__main__":
    unittest.main()
