# Стенд, на котором стоит весь остальной набор. Если он лжёт — лжёт всё:
# зелёный тест, где поддельный claude не вызывался, и песочница, утёкшая
# в настоящий дом, выглядят одинаково успешными.
import os
import shutil
import sys
import tempfile
import unittest

try:
    import pwd            # POSIX only; the test that needs it skips without it
except ImportError:
    pwd = None

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import harness  # noqa: E402
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


class TestSandboxGuardHoles(unittest.TestCase):
    """Шесть дыр, каждая из которых однажды кончалась бы стёртым деревом.

    Правило этого класса: жертвой всегда служит каталог во временном. Ни один
    тест здесь не создаёт опасный корень «чтобы посмотреть» — те, что должны
    быть отвергнуты, либо не существуют вовсе, либо существуют во временном.
    """

    def _tmpdir(self, prefix):
        d = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def _set_env(self, **kw):
        for var, value in kw.items():
            self.addCleanup(_restore, var, os.environ.get(var))
            os.environ[var] = value

    def _set_module_global(self, name, value):
        # getattr with a default, and the cleanup restores absence as absence:
        # the test must reach its assertion even against a harness that has no
        # such global, or it proves nothing about the harness that does.
        missing = object()
        old = getattr(harness, name, missing)
        if old is missing:
            self.addCleanup(lambda: delattr(harness, name))
        else:
            self.addCleanup(setattr, harness, name, old)
        setattr(harness, name, value)

    def _set_tempfile_tempdir(self, value):
        old = tempfile.tempdir
        self.addCleanup(setattr, tempfile, "tempdir", old)
        tempfile.tempdir = value

    # ── СЕРЬЁЗНАЯ 1: белый список стоит на переменной окружения ──

    def test_the_anchor_is_frozen_at_import_not_read_at_check_time(self):
        # Живой tempfile.gettempdir() — это TMPDIR и изменяемая глобаль
        # tempfile.tempdir, обе в руках у того, кого ограда сторожит. Корень
        # здесь заведомо несуществующий: конструктор обязан отказать, не
        # создав ничего, поэтому смотреть тут не на что и создавать нечего.
        hostile = os.path.join(os.sep, "cckit-no-such-anchor")
        self._set_tempfile_tempdir(hostile)
        self._set_env(TMPDIR=hostile)
        with self.assertRaises(AssertionError) as cm:
            Sandbox(root=os.path.join(hostile, "root"))
        self.assertIn("временного", str(cm.exception))

    def test_tmpdir_is_saved_and_restored_by_the_sandbox(self):
        self.assertIn("TMPDIR", harness.VARS,
                      "TMPDIR не сохраняется: тест, сдвинувший его, сдвинет якорь всем")
        self._set_env(TMPDIR=self._tmpdir("cckit-tmpdir-"))
        mine = os.environ["TMPDIR"]
        with Sandbox():
            pass
        self.assertEqual(os.environ.get("TMPDIR"), mine)

    @unittest.skipIf(pwd is None, "нет базы паролей — дом не спросить мимо окружения")
    def test_a_root_inside_the_real_home_is_refused_whatever_the_anchor_says(self):
        # Якорь, снятый при импорте, всё равно взят из окружения, которое
        # могло быть враждебным ДО импорта. Здесь враждебность доведена до
        # предела: якорь объявлен настоящим домом. Второе условие — то, что
        # спрашивает базу паролей, а не окружение, — обязано сработать всё
        # равно. Путь не существует и не создаётся.
        home = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
        self._set_module_global("_ANCHOR", home)
        self._set_tempfile_tempdir(home)
        victim = os.path.join(home, ".cckit-guard-probe-not-real", "assistants", "x")
        with self.assertRaises(AssertionError) as cm:
            Sandbox(root=victim)
        self.assertIn("дом", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(home, ".cckit-guard-probe-not-real")),
                         "проверка создала каталог в настоящем доме")

    # ── СЕРЬЁЗНАЯ 2: ограду не спрашивают в момент удаления ──

    def test_a_root_swapped_after_entry_is_refused_at_delete(self):
        # sb.root — обычный атрибут. Между входом и выходом его можно
        # переназначить на что угодно, и раньше выход это «что угодно» сносил.
        # Жертва — подставной дом во временном, с файлом внутри.
        stand_in = os.path.join(self._tmpdir("cckit-victim-"), "me")
        os.makedirs(stand_in)
        learned = os.path.join(stand_in, "LEARNED.md")
        with open(learned, "w", encoding="utf-8") as fh:
            fh.write("накопленная память")
        self._set_env(HOME=stand_in, USERPROFILE=stand_in)

        sb = Sandbox()
        sb.__enter__()
        self.addCleanup(shutil.rmtree, sb.root, True)
        sb.root = stand_in
        with self.assertRaises(AssertionError):
            sb.__exit__(None, None, None)
        self.assertTrue(os.path.exists(learned), "подменённый корень был стёрт")
        self.assertEqual(os.environ.get("HOME"), stand_in,
                         "окружение не восстановлено, хотя уборка отказалась")

    # ── СЕРЬЁЗНАЯ 3: относительный корень ──

    def test_a_relative_root_does_not_follow_the_cwd(self):
        # Корень «root», проверенный из одного каталога и удалённый из
        # другого, удаляет другое дерево. Оба каталога — во временном.
        base = self._tmpdir("cckit-relative-")
        mine = os.path.join(base, "a", "root")
        victim = os.path.join(base, "b", "root")
        os.makedirs(mine)
        os.makedirs(victim)
        keep = os.path.join(victim, "KEEP.md")
        with open(keep, "w", encoding="utf-8") as fh:
            fh.write("чужое дерево")

        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(os.path.join(base, "a"))
        sb = Sandbox(root="root")
        sb.__enter__()
        os.chdir(os.path.join(base, "b"))
        sb.__exit__(None, None, None)

        self.assertTrue(os.path.exists(keep), "выход удалил дерево по новому cwd")
        self.assertFalse(os.path.exists(mine), "выход не убрал собственный корень")

    # ── МЕЛКИЕ ──

    def test_a_cleanup_that_did_not_clean_up_is_loud(self):
        # ignore_errors=True глотает всё: симлинк вместо корня rmtree отвергает,
        # и раньше выход об этом молчал, оставляя корень навсегда.
        target = self._tmpdir("cckit-link-target-")
        keep = os.path.join(target, "KEEP.md")
        with open(keep, "w", encoding="utf-8") as fh:
            fh.write("цель симлинка")
        link = os.path.join(self._tmpdir("cckit-link-"), "root")
        os.symlink(target, link)

        sb = Sandbox()
        sb.__enter__()
        self.addCleanup(shutil.rmtree, sb.root, True)
        sb.root = link
        with self.assertRaises(AssertionError) as cm:
            sb.__exit__(None, None, None)
        self.assertIn("не убрана", str(cm.exception))
        self.assertTrue(os.path.exists(keep), "rmtree прошёл сквозь симлинк")

    def test_exit_without_enter_is_a_no_op(self):
        # Падение AttributeError: '_saved' в finally прячет настоящую ошибку
        # теста и оставляет окружение несобранным.
        Sandbox().__exit__(None, None, None)

    def test_an_empty_root_is_refused(self):
        # realpath('') — это cwd, то есть проверялся совсем не тот путь; а
        # дальше '' молча подменялся на mkdtemp. Из временного каталога — где
        # cwd белый список проходит — раньше это было зелено.
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self._tmpdir("cckit-empty-"))
        with self.assertRaises(AssertionError) as cm:
            Sandbox(root="")
        self.assertIn("пуст", str(cm.exception))

    def test_a_case_variant_of_the_home_is_refused(self):
        # normcase на macOS — тождество, realpath регистр не сворачивает:
        # защиту от регистра даёт только сам диск, и спросить его надо.
        outer = self._tmpdir("cckit-case-")
        mixed = os.path.join(outer, "Me")
        other = os.path.join(outer, "me")
        os.makedirs(mixed)
        if not os.path.isdir(other):
            self.skipTest("файловая система различает регистр — подменять нечего")
        self._set_env(HOME=mixed, USERPROFILE=mixed)
        with self.assertRaises(AssertionError) as cm:
            Sandbox(root=other)
        self.assertIn("дом", str(cm.exception))

if __name__ == "__main__":
    unittest.main()
