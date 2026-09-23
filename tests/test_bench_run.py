# Стенд меряет варианты роли. Эти тесты держат то, из-за чего измерение
# превращается в суеверие: прогон, чей промпт не дошёл, записанный проигрышем;
# песочница, которой на самом деле нет; и ограда, сквозь которую случай
# «внеси правку в src/» уходит в настоящий проект.
#
# Здесь НЕТ ни одного теста, запускающего `claude`: набор гоняют часто, а
# каждый такой запуск — деньги владельца. Всё, что требует ребёнка,
# проверяется поддельным claude отдельно.
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import cckit_bench as bench


class TestCases(unittest.TestCase):
    def _cases(self, data):
        d = tempfile.mkdtemp(prefix="cckit-test-")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "c.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return p

    def test_load_cases_requires_id_and_prompt(self):
        cases = bench.load_cases(self._cases([{"id": "a", "prompt": "hi"}]))
        self.assertEqual([(c["id"], c["prompt"]) for c in cases], [("a", "hi")])

    def test_load_cases_rejects_a_case_without_a_prompt(self):
        with self.assertRaises(ValueError):
            bench.load_cases(self._cases([{"id": "a"}]))

    def test_load_cases_rejects_two_cases_with_one_id(self):
        # Одинаковые id сливаются в один каталог песочницы и в одну строку
        # отчёта: два случая становятся одним, и никто этого не видит.
        with self.assertRaises(ValueError):
            bench.load_cases(self._cases([{"id": "a", "prompt": "x"},
                                          {"id": "a", "prompt": "y"}]))

    def test_the_shipped_cases_file_loads(self):
        p = os.path.join(os.path.dirname(__file__), "..", "bench", "cases",
                         "design-scout.json")
        self.assertTrue([c["id"] for c in bench.load_cases(p)])


class TestScoringHonesty(unittest.TestCase):
    def test_a_run_whose_prompt_did_not_arrive_is_not_scorable(self):
        # Поломка, выглядящая ровно как «кандидат хуже».
        rec = {"variant": "cand", "case": "a", "ok": True, "prompt_ok": False}
        self.assertFalse(bench.scorable(rec))

    def test_a_run_that_errored_is_not_scorable(self):
        rec = {"variant": "cand", "case": "a", "ok": False, "prompt_ok": True}
        self.assertFalse(bench.scorable(rec))

    def test_a_clean_run_is_scorable(self):
        rec = {"variant": "cand", "case": "a", "ok": True, "prompt_ok": True}
        self.assertTrue(bench.scorable(rec))

    def test_an_empty_answer_is_a_failed_run_not_a_bad_answer(self):
        # Судья, которому показали пустоту, назовёт её проигрышем — то же
        # суеверие, другим путём. Пустой ответ не доходит до судьи вовсе.
        self.assertEqual(bench.outcome({"result": "  \n", "session_id": "s"}, None),
                         (False, "ответ пуст"))

    def test_a_run_with_an_answer_is_a_measurement(self):
        self.assertEqual(bench.outcome({"result": "ответ", "session_id": "s"}, None),
                         (True, None))

    def test_an_is_error_result_is_a_failed_run(self):
        ok, note = bench.outcome({"result": "x", "is_error": True,
                                  "subtype": "error_max_budget"}, None)
        self.assertEqual((ok, note), (False, "error_max_budget"))


class TestSandbox(unittest.TestCase):
    def test_each_run_gets_its_own_sandbox_directory(self):
        a = bench.sandbox_dir("/tmp/run1", "pe", "case1", 1)
        b = bench.sandbox_dir("/tmp/run1", "pe", "case1", 2)
        self.assertNotEqual(a, b)

    def test_sandbox_is_inside_the_run_and_not_in_the_project(self):
        run_dir = os.path.join(bench.runs_dir(), "smoke-1")
        d = bench.sandbox_dir(run_dir, "pe", "case1", 1)
        self.assertTrue(d.startswith(run_dir + os.sep))
        self.assertFalse(d.startswith(os.path.expanduser("~/cckit-plugin")))

    def test_a_case_id_cannot_walk_out_of_the_run(self):
        # Файл случаев — данные. id вида "../../etc" не должен стать путём:
        # после нормализации песочница всё ещё лежит внутри прогона, одним
        # уровнем ниже boxes.
        d = bench.sandbox_dir("/tmp/run1", "pe", "../../etc", 1)
        self.assertEqual(os.path.dirname(os.path.normpath(d)), "/tmp/run1/boxes")
        self.assertTrue(os.path.normpath(d).startswith("/tmp/run1" + os.sep))

    def test_runs_dir_is_resolved_per_call_not_frozen_at_import(self):
        # Замороженный путь писал бы прогоны в настоящий дом владельца прямо
        # из-под теста, который думает, что сидит во временном.
        d = tempfile.mkdtemp(prefix="cckit-test-")
        self.addCleanup(shutil.rmtree, d, True)
        for var in ("HOME", "USERPROFILE"):
            self.addCleanup(os.environ.__setitem__, var, os.environ.get(var, ""))
            os.environ[var] = d
        self.assertTrue(bench.runs_dir().startswith(d))


class TestFence(unittest.TestCase):
    """Случай `refuse-to-build` велит ребёнку добавить файл в src/. Ограда —
    то, что делает этот случай измерением, а не правкой чужого проекта."""

    def test_the_fence_denies_writing_the_shell_and_the_net(self):
        off = bench.disallowed_tools()
        for tool in ("Write", "Edit", "NotebookEdit", "Bash", "Monitor",
                     "Agent", "SendMessage", "WebFetch"):
            self.assertIn(tool, off, tool + " не запрещён — прогон может выйти наружу")

    def test_the_fence_leaves_reading_alone(self):
        off = bench.disallowed_tools()
        for tool in ("Read", "Grep", "Glob"):
            self.assertNotIn(tool, off, tool + " запрещён — случай нечем решать")

    def test_the_fence_comes_from_the_installers_groups_not_a_second_copy(self):
        # Список рук, написанный здесь, разъедется с CAPS установщика — так уже
        # было с shell/Monitor. Ограда у стенда и у установщика одна.
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
        import cckit_assistant
        self.assertEqual(bench.disallowed_tools(),
                         cckit_assistant.caps_to_disallowed(set(cckit_assistant.BASE_CAPS)))


if __name__ == "__main__":
    unittest.main()
