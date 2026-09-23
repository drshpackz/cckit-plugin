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
import cckit_assistant  # noqa: E402


def _restore(var, value):
    if value is None:
        os.environ.pop(var, None)
    else:
        os.environ[var] = value


def _verdict(launch):
    """Прогоняет пример-подопытный и возвращает его вердикт как
    (прогонов, ошибок, падений). Пример утверждает ровно то, чем настоящие
    тесты стенда защищаются от зелени вхолостую — что поддельный claude был
    вызван. Класс объявлен внутри: на уровне модуля его подобрал бы discover и
    погнал как обычный тест."""

    class ExpectsACall(unittest.TestCase):
        def runTest(self):
            with Sandbox() as sb:
                if launch:
                    sb.set_reply("ok")
                    core.run_claude(sb.project,
                                    core.launch_argv("q", sb.project, [], True, "0.10",
                                                     extra=["--output-format", "json"]))
                self.assertEqual(len(sb.calls()), 1, "фальшивый claude не вызывался")

    r = unittest.TestResult()
    ExpectsACall().run(r)
    return (r.testsRun, len(r.errors), len(r.failures))


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

    def test_only_a_temporary_root_is_accepted(self):
        # Отвергаемые корни здесь настоящие — настоящий дом, '/', его родитель.
        # Создавать их тест не может и не должен: проверяется конструктор,
        # который обязан отказать ДО того, как появится первый каталог, и
        # задолго до rmtree на выходе. Поэтому ни одного `with` в этом цикле.
        real = os.path.expanduser("~")
        for root in (real, os.sep, os.path.dirname(real),
                     os.path.dirname(os.path.dirname(real))):
            with self.assertRaises(AssertionError, msg="впущен корень " + root) as cm:
                Sandbox(root=root)
            msg = str(cm.exception)
            self.assertIn(root, msg, "в отказе не назван корень")
            self.assertTrue("отвергнут" in msg and ("временного" in msg or "дом" in msg),
                            "в отказе не названа причина: " + msg)

    def test_a_subdirectory_of_the_temporary_directory_is_accepted(self):
        root = tempfile.mkdtemp(prefix="cckit-guard-ok-")
        self.addCleanup(shutil.rmtree, root, True)
        with Sandbox(root=root) as sb:
            self.assertTrue(os.path.isdir(sb.home))
            self.assertTrue(sb.home.startswith(root + os.sep))
        self.assertFalse(os.path.exists(root), "песочница не убрала за собой")

    def test_projects_dir_follows_the_sandbox(self):
        # Resolved per call: a module that computed it at import time would
        # keep pointing at the real home for the whole test run.
        with Sandbox() as sb:
            self.assertTrue(core.projects_dir().startswith(sb.home))

    def test_installer_roots_follow_the_sandbox(self):
        # Тот же вопрос к установщику: его корни считаются при вызове, иначе
        # первый же тест установки запишет в настоящий ~/.cckit, где живёт
        # рабочий design-scout@chiavs-code.
        self.addCleanup(_restore, "CCKIT_LIBRARY", os.environ.get("CCKIT_LIBRARY"))
        os.environ["CCKIT_LIBRARY"] = "/настоящая/библиотека"
        with Sandbox() as sb:
            got = [cckit_assistant.library_dir(), cckit_assistant.assistants_dir(),
                   cckit_assistant.claude_json()]
            self.assertEqual([p.startswith(sb.home + os.sep) for p in got],
                             [True, True, True], got)
        self.assertEqual(os.environ.get("CCKIT_LIBRARY"), "/настоящая/библиотека",
                         "CCKIT_LIBRARY не восстановлена на выходе")


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
        # Главный отказ любого набора — зелёный тест, который ничего не звал.
        # Проверяем это единственным честным способом: гоняем пример, который
        # ждёт вызова, и смотрим на его вердикт. Без вызова он обязан упасть,
        # с вызовом — пройти; вторая половина доказывает, что падение не от
        # сломанного стенда. (прогонов, ошибок, падений)
        self.assertEqual(_verdict(launch=False), (1, 0, 1),
                         "пример прошёл, хотя поддельный claude не вызывался")
        self.assertEqual(_verdict(launch=True), (1, 0, 0),
                         "пример упал даже при настоящем вызове — лжёт стенд")

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
