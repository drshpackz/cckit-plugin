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
