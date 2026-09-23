# Стенд, на котором стоит весь остальной набор. Если он лжёт — лжёт всё:
# зелёный тест, где поддельный claude не вызывался, и песочница, утёкшая
# в настоящий дом, выглядят одинаково успешными.
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
from harness import Sandbox  # noqa: E402
import cckit_core as core  # noqa: E402


def _restore(var, value):
    if value is None:
        os.environ.pop(var, None)
    else:
        os.environ[var] = value


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

    def test_a_root_holding_the_real_home_is_refused(self):
        # У владельца живой ассистент под настоящим ~/.cckit. Ограда, которую
        # нельзя заставить сработать, ничем не отличается от её отсутствия —
        # но заставлять её срабатывать на настоящем доме нельзя: сломанная
        # ограда стёрла бы его. Поэтому «настоящий» дом здесь подставной, и
        # цена ошибки — временный каталог.
        outer = tempfile.mkdtemp(prefix="cckit-guard-")
        self.addCleanup(shutil.rmtree, outer, True)
        stand_in = os.path.join(outer, "me")
        os.makedirs(stand_in)
        for var in ("HOME", "USERPROFILE"):
            self.addCleanup(_restore, var, os.environ.get(var))
            os.environ[var] = stand_in

        entered = []
        with self.assertRaises(AssertionError):
            with Sandbox(root=outer) as sb:
                entered.append(sb.home)
        self.assertEqual(entered, [], "песочница впустила дом внутрь удаляемого дерева")
        self.assertEqual(os.environ.get("HOME"), stand_in, "окружение поехало до ограды")
        self.assertFalse(os.path.exists(os.path.join(outer, "home")),
                         "ограда сработала, но каталог уже создала")

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
            # realpath on both sides: the child reports a cwd with symlinks
            # resolved (/var -> /private/var on macOS), the sandbox does not.
            self.assertEqual(os.path.normcase(os.path.realpath(calls[0]["cwd"])),
                             os.path.normcase(os.path.realpath(sb.project)))

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
