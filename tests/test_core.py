# Установщик и стенд запускают ребёнка одним и тем же кодом. Эти тесты держат
# именно то, что разъехалось однажды: ограду запуска и чтение транскрипта.
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import cckit_core as core
import cckit_assistant


class TestIsolation(unittest.TestCase):
    def test_link_vars_are_stripped_and_harbor_disabled(self):
        for v in ("CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_SESSION_ID"):
            self.addCleanup(os.environ.pop, v, None)
        os.environ["CLAUDE_CODE_MESSAGING_SOCKET"] = "/tmp/fake.sock"
        os.environ["CLAUDE_CODE_SESSION_ID"] = "fake-session"
        env = core.isolated_env()
        for v in core.LINK_VARS:
            self.assertNotIn(v, env, v + " survived isolation")
        self.assertEqual(env.get("CLAUDE_CODE_HARBOR_KITE"), "0")

    def test_launch_argv_always_carries_a_budget(self):
        argv = core.launch_argv("hi", "/tmp", ["Bash"], True, "0.50")
        self.assertIn("--max-budget-usd", argv)
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.50")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("Bash", argv)


class TestInstallerWrapper(unittest.TestCase):
    def test_wrapper_argv_is_byte_for_byte_what_it_was(self):
        # Снимок снят с кода ДО выделения ядра: если обёртка съедет, съедет и
        # команда, под которой на самом деле работает установленный ассистент.
        self.assertEqual(
            cckit_assistant.launch_argv("/h", "/p", "q", {"read"}, "0.5"),
            ["claude", "-p", "q", "--add-dir", "/p", "--max-budget-usd", "0.5",
             "--disallowedTools", "Agent", "Artifact", "ArtifactComments",
             "ArtifactData", "Bash", "CronCreate", "CronDelete", "CronList",
             "DesignSync", "Edit", "EnterWorktree", "ExitWorktree", "ListAgents",
             "Monitor", "NotebookEdit", "PushNotification", "RemoteTrigger",
             "ReportFindings", "ScheduleWakeup", "SendMessage", "Skill",
             "TaskStop", "ToolSearch", "WebFetch", "WebSearch", "Workflow",
             "Write", "--strict-mcp-config"])


class TestClaudeIsFound(unittest.TestCase):
    """`claude` на Windows — это npm-шим claude.cmd, а subprocess запускает
    через CreateProcess, который дописывает только '.exe' и PATHEXT не смотрит:
    голое имя там не находится вовсе. Поэтому имя резолвится через
    shutil.which (он PATHEXT читает) и уходит в запуск абсолютным путём.

    Сам PATHEXT с macOS не проверить. Проверяется вторая половина того же
    исправления, наблюдаемая и здесь: имя разрешает вызывающая сторона, один
    раз и в абсолютный путь, — а не execvp уже внутри ребёнка, у которого свой
    cwd."""

    def _shim(self, mark):
        d = tempfile.mkdtemp(prefix="cckit-test-")
        self.addCleanup(shutil.rmtree, d, True)
        out = os.path.join(d, "who")
        with open(os.path.join(d, "claude"), "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nprintf %%s %s > "%s"\nprintf {}\n' % (mark, out))
        os.chmod(os.path.join(d, "claude"), 0o755)
        return d, out

    def test_the_name_is_resolved_by_the_caller_not_by_the_child(self):
        mine, mine_out = self._shim("MINE")
        theirs, theirs_out = self._shim("THEIRS")
        self.addCleanup(os.chdir, os.getcwd())
        self.addCleanup(os.environ.__setitem__, "PATH", os.environ.get("PATH", ""))
        os.chdir(mine)
        os.environ["PATH"] = "."          # разрешается от cwd — чьего?

        res, err = core.run_claude(theirs, ["claude", "-p", "q"])
        self.assertEqual((res, err), ({}, None))
        self.assertTrue(os.path.exists(mine_out), "запустился не тот claude")
        self.assertFalse(os.path.exists(theirs_out),
                         "имя разрешил ребёнок в своём cwd — как до починки")

    def test_a_missing_claude_is_a_sentence_not_a_traceback(self):
        res, err = core.run_claude(tempfile.gettempdir(), ["cckit-no-such-claude"])
        self.assertIsNone(res)
        self.assertIn("не найден в PATH", err)


class TestTranscript(unittest.TestCase):
    def _transcript_dir(self):
        # Каталог живёт ровно до конца теста: набор, оставляющий мусор в
        # $TMPDIR, засоряет машину владельца на каждом прогоне.
        d = tempfile.mkdtemp(prefix="cckit-test-")
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_system_prompt_parts_reads_the_snapshot(self):
        p = os.path.join(self._transcript_dir(), "s.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "content": "x"}) + "\n")
            fh.write(json.dumps({"type": "attachment", "attachment": {
                "type": "prompt_snapshot", "systemPrompt": ["BODY", "more"]}}) + "\n")
        self.assertEqual(core.system_prompt_parts(p), ["BODY", "more"])

    def test_system_prompt_parts_returns_none_without_a_snapshot(self):
        p = os.path.join(self._transcript_dir(), "s.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user"}) + "\n")
        self.assertIsNone(core.system_prompt_parts(p))


if __name__ == "__main__":
    unittest.main()


class TestDiagnosticReproducesNothing(unittest.TestCase):
    """Диагностика расхождения промптов не имеет права воспроизводить промпт.

    Прежняя версия печатала первые 70 знаков доставленного. Если роль не
    дошла, это чужой системный промпт — и он уезжал в results.jsonl и на
    терминал.
    """

    NEEDLE = "СЕКРЕТНАЯ-СТРОКА-КОТОРОЙ-НЕ-ДОЛЖНО-БЫТЬ-В-ОТЧЁТЕ"

    def test_the_needle_is_not_echoed_into_the_note(self):
        delivered = "Начало. " + self.NEEDLE + " Конец."
        note = core.describe_mismatch(delivered, "совсем другое тело роли")
        self.assertNotIn(self.NEEDLE, note)
        for n in (12, 16, 24):
            self.assertNotIn(self.NEEDLE[:n], note,
                             "в отчёт утекли первые %d знаков промпта" % n)

    def test_the_note_still_answers_what_the_echo_answered(self):
        # Латиница нарочно: общий префикс здесь пересчитывается глазами и не
        # зависит от того, как считать кириллицу.
        delivered, expected = "abcdefGHI", "abcdefXYZ"
        note = core.describe_mismatch(delivered, expected)
        self.assertIn("доставлено 9 знаков", note)
        self.assertIn("ожидалось 9", note)
        self.assertIn(core.fingerprint(delivered), note)
        self.assertIn("совпадает первых 6", note)

    def test_the_fingerprint_separates_and_does_not_restore(self):
        a, b = core.fingerprint("роль А"), core.fingerprint("роль Б")
        self.assertNotEqual(a, b)
        self.assertEqual(a, core.fingerprint("роль А"))
        self.assertEqual(len(a), 12)

    def test_an_empty_delivered_prompt_is_described_not_crashed(self):
        self.assertIn("доставлено 0 знаков", core.describe_mismatch("", "тело"))
        self.assertIn("доставлено 0 знаков", core.describe_mismatch(None, "тело"))
