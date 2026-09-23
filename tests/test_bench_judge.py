# Судейство. Две мысли, ради которых оно существует, и обе ломаются молча:
#
#  1. Судья не должен знать, какой вариант перед ним. Имя варианта лежит в пути
#     песочницы, путь попадает в ответ ребёнка, и модель, прочитавшая путь,
#     знает ответ до того, как начала сравнивать.
#  2. Разница меньше шума — не разница. Назвать победителя на шести сравнениях
#     хуже, чем не назвать никого: цифра запомнится, а порог нет.
#
# Ни один тест здесь не запускает настоящий `claude`. Те, которым нужен
# ребёнок, поднимают поддельного судью и ставят PATH РАВНЫМ одному каталогу с
# ним: при таком PATH настоящий недостижим в принципе, и промах стоит ошибки,
# а не денег.
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import cckit_bench as bench  # noqa: E402

# Поддельный судья: выбирает тот ответ, в котором лежит метка ХОРОШИЙ, где бы
# тот ни стоял. Судья, читающий только первым, на нём виден сразу.
FAKE_JUDGE = r'''
import json, os, sys
p = sys.argv[sys.argv.index("-p") + 1]
calls = os.environ.get("CCKIT_TEST_CALLS")
if calls:
    with open(calls, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "prompt": p}, ensure_ascii=False) + "\n")
said = "ничья"
i = p.find("ХОРОШИЙ")
if i >= 0:
    h = p.rfind("ОТВЕТ ", 0, i)
    said = p[h + len("ОТВЕТ "):p.index(":", h)]
sys.stdout.write(json.dumps({"result": said, "session_id": "j", "total_cost_usd": 0.01}))
'''


class TestBlinding(unittest.TestCase):
    def test_label_does_not_leak_the_variant_name(self):
        lab = bench.blind_label("candidate-v2", "case1", "A")
        self.assertNotIn("candidate", lab)
        self.assertNotIn("v2", lab)

    def test_same_variant_and_case_label_differs_by_position(self):
        self.assertNotEqual(bench.blind_label("pe", "c1", "A"),
                            bench.blind_label("pe", "c1", "B"))

    def test_the_two_answers_of_one_comparison_never_share_a_label(self):
        # Совпади метки — выбор судьи нечитаем, а «непонятно» пошло бы в счёт.
        self.assertNotEqual(bench.blind_label("base", "c1", "A"),
                            bench.blind_label("pe", "c1", "B"))

    def test_a_sandbox_path_in_an_answer_is_scrubbed(self):
        box = "/r/boxes/pe-c1-r1"
        out = bench.scrub("я записал в %s/note.md" % box, [box, "/r"])
        self.assertNotIn("pe", out)

    def test_the_secrets_carry_both_forms_of_every_path(self):
        # Ребёнок называет свой каталог разрешённым (/private/var/... на macOS
        # для песочницы /var/...), а в записи лежит тот, что строил стенд.
        # Подстановка одной формы не трогает другую, и имя варианта уезжает.
        rec = {"sandbox": os.path.join(tempfile.gettempdir(), "boxes", "pe-c1-r1")}
        got = bench.secrets_of([rec], "/r")
        self.assertIn(rec["sandbox"], got)
        self.assertIn(os.path.realpath(rec["sandbox"]), got)

    def test_scrubbing_leaves_the_rest_of_the_answer_alone(self):
        text = "в src/a.ts:12 база данных на месте"
        self.assertEqual(bench.scrub(text, ["/r/boxes/base-c1-r1", "/r"]), text)


class TestNoise(unittest.TestCase):
    def test_noise_floor_falls_as_comparisons_grow(self):
        self.assertGreater(bench.noise_floor(4), bench.noise_floor(100))

    def test_a_margin_under_the_floor_is_not_a_win(self):
        # 3 из 5: перевес 0.2 при пороге 0.447.
        self.assertEqual(bench.verdict(wins=3, losses=2, ties=0), "не отличить")

    def test_a_clear_margin_is_a_win(self):
        self.assertEqual(bench.verdict(wins=18, losses=2, ties=0), "B лучше")

    def test_no_scorable_comparisons_is_not_a_tie(self):
        self.assertEqual(bench.verdict(wins=0, losses=0, ties=0), "нечего сравнивать")

    def test_one_comparison_never_names_a_winner(self):
        # Перевес ровно равен порогу — то есть весь он и есть шум.
        self.assertEqual(bench.verdict(wins=1, losses=0, ties=0), "не отличить")

    def test_three_of_four_is_still_noise(self):
        self.assertEqual(bench.verdict(wins=3, losses=1, ties=0), "не отличить")

    def test_a_losing_candidate_is_named_too(self):
        self.assertEqual(bench.verdict(wins=2, losses=18, ties=0), "A лучше")


class TestReadingTheJudge(unittest.TestCase):
    LABELS = {"A1f2": "base", "B9ab": "pe"}

    def test_one_label_is_a_choice(self):
        self.assertEqual(bench.read_pick("B9ab", self.LABELS)[0], "pe")

    def test_a_label_inside_a_sentence_still_counts(self):
        self.assertEqual(bench.read_pick("Лучше A1f2, он со ссылками.",
                                         self.LABELS)[0], "base")

    def test_the_word_tie_is_a_tie(self):
        self.assertEqual(bench.read_pick("ничья", self.LABELS)[0], bench.TIE)

    def test_silence_is_not_a_tie(self):
        # Молчащий судья — не «оба одинаковы», это отсутствие измерения.
        self.assertIsNone(bench.read_pick("", self.LABELS)[0])

    def test_both_labels_named_is_not_a_tie(self):
        self.assertIsNone(bench.read_pick("A1f2 против B9ab", self.LABELS)[0])


class TestJudgeFence(unittest.TestCase):
    def test_the_judge_may_not_go_and_look(self):
        # Слепота меток держится только на том, что судье нечем открыть
        # песочницу и прочитать карточку варианта.
        off = bench.judge_disallowed()
        for tool in ("Read", "Grep", "Glob", "Bash", "WebFetch", "Skill", "Agent"):
            self.assertIn(tool, off, tool + " оставлен судье — слепота показная")

    def test_the_fence_comes_from_the_installers_groups_not_a_second_copy(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
        import cckit_assistant
        self.assertEqual(bench.judge_disallowed(),
                         cckit_assistant.caps_to_disallowed(set()))


class TestJudging(unittest.TestCase):
    """Сквозь cmd_judge, на поддельном судье."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cckit-judge-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = os.path.join(self.tmp, "run")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.run_dir)
        os.makedirs(self.project)
        for var in ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "PATH"):
            self.addCleanup(os.environ.__setitem__, var, os.environ.get(var, ""))
        os.environ["HOME"] = os.environ["USERPROFILE"] = self.tmp
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, ".claude")

    def _results(self, recs):
        with open(os.path.join(self.run_dir, "results.jsonl"), "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _rec(self, variant, case, answer, **kw):
        rec = {"variant": variant, "case": case, "attempt": 1, "ok": True,
               "prompt_ok": True, "prompt": "разбери %s" % case, "answer": answer,
               "sandbox": os.path.join(self.run_dir, "boxes",
                                       "%s-%s-r1" % (variant, case))}
        rec.update(kw)
        return rec

    def _only_on_path(self, body=None):
        """PATH ровно из одного каталога: настоящий claude недостижим."""
        binp = os.path.join(self.tmp, "bin")
        os.makedirs(binp, exist_ok=True)
        if body is not None:
            p = os.path.join(binp, "claude")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("#!" + sys.executable + "\n" + body)
            os.chmod(p, 0o755)
        os.environ["PATH"] = binp
        return binp

    def _judge(self, *extra):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bench.cmd_judge(["--run", self.run_dir, "--a", "base", "--b", "pe",
                                  "--project", self.project] + list(extra))
        return rc, buf.getvalue()

    def _verdicts(self):
        with open(os.path.join(self.run_dir, "verdicts.jsonl"), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_the_better_answer_wins_in_both_orders(self):
        # Ровно тот провал, который нельзя увидеть на одном порядке: если метку
        # сопоставить с позицией, а не с вариантом, победа во втором порядке
        # запишется проигрышем и обе строки схлопнутся в ничью.
        self._results([self._rec("base", "c1", "плохая догадка"),
                       self._rec("pe", "c1", "ХОРОШИЙ разбор, src/a.ts:12")])
        self._only_on_path(FAKE_JUDGE)
        rc, out = self._judge()
        self.assertEqual(rc, 0)
        self.assertEqual([(v["swapped"], v["picked"]) for v in self._verdicts()],
                         [(False, "pe"), (True, "pe")])
        self.assertIn("pe выиграл 2", out)

    def test_the_judge_is_never_shown_the_sandbox_path(self):
        self._results([self._rec("base", "c1", "плохая догадка"),
                       self._rec("pe", "c1", "ХОРОШИЙ разбор, см. %s/note.md"
                                 % os.path.join(self.run_dir, "boxes", "pe-c1-r1"))])
        self._only_on_path(FAKE_JUDGE)
        calls = os.path.join(self.tmp, "calls.jsonl")
        self.addCleanup(os.environ.pop, "CCKIT_TEST_CALLS", None)
        os.environ["CCKIT_TEST_CALLS"] = calls
        self._judge()
        with open(calls, encoding="utf-8") as fh:
            asked = [json.loads(l) for l in fh if l.strip()]
        self.assertTrue(asked)
        for call in asked:
            self.assertNotIn("pe-c1-r1", call["prompt"], "имя варианта дошло до судьи")

    def test_a_judge_that_cannot_be_reached_is_not_a_tie(self):
        # Не дозвонились — не ничья. Ничья это то, что судья сказал.
        self._results([self._rec("base", "c1", "а"), self._rec("pe", "c1", "б")])
        self._only_on_path(None)
        rc, out = self._judge()
        self.assertEqual(rc, 0)
        self.assertIn("ничьих 0", out)
        self.assertIn("нечего сравнивать", out)
        self.assertEqual([v["picked"] for v in self._verdicts()], [None, None])

    def test_a_case_only_one_variant_could_run_is_not_compared(self):
        # Прогон, чей промпт не дошёл, не становится проигрышем и на суде.
        self._results([self._rec("base", "c1", "плохая догадка"),
                       self._rec("pe", "c1", "ХОРОШИЙ разбор"),
                       self._rec("base", "c2", "что-то"),
                       self._rec("pe", "c2", "", ok=True, prompt_ok=False)])
        self._only_on_path(FAKE_JUDGE)
        rc, out = self._judge()
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(v["case"] for v in self._verdicts()), ["c1", "c1"])
        self.assertIn("c2", out)

    def test_an_unknown_variant_name_is_an_error_not_an_empty_report(self):
        self._results([self._rec("base", "c1", "а"), self._rec("pe", "c1", "б")])
        self._only_on_path(None)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = bench.cmd_judge(["--run", self.run_dir, "--a", "bas", "--b", "pe",
                                  "--project", self.project])
        self.assertEqual(rc, 2)
        self.assertIn("bas", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
