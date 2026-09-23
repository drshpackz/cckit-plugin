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

# Судья из первого платного прогона: на длинных содержательных сравнениях он
# объявлял, что сейчас сверится с файлами, и выдавал сырой синтаксис вызова —
# а слово «ничья» оказывалось внутри того же текста и уходило в счёт ничьёй.
FAKE_JUDGE_REACHES = r'''
import json, os, sys
p = sys.argv[sys.argv.index("-p") + 1]
calls = os.environ.get("CCKIT_TEST_CALLS")
if calls:
    with open(calls, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "prompt": p}, ensure_ascii=False) + "\n")
if "ДЛИННЫЙ" in p:
    said = ("I'll verify both answers against the actual files.\n"
            '<invoke name="Bash">\n'
            '<parameter name="command">ls -la</parameter>\n'
            "а пока, пожалуй, ничья")
else:
    said = "ничья"
    i = p.find("ХОРОШИЙ")
    if i >= 0:
        h = p.rfind("ОТВЕТ ", 0, i)
        said = p[h + len("ОТВЕТ "):p.index(":", h)]
sys.stdout.write(json.dumps({"result": said, "session_id": "j", "total_cost_usd": 0.01}))
'''

# Тот же судья, но в его тексте нет ни метки, ни слова «ничья»: такое
# сравнение считалось выпавшим и раньше. Здесь виден ровно второй изъян —
# планка, посчитанная от уцелевших.
FAKE_JUDGE_MUTE_ON_LONG = FAKE_JUDGE_REACHES.replace(
    '"а пока, пожалуй, ничья")', '"")')


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

    def test_a_clean_sweep_is_no_verdict_when_half_the_judging_fell_out(self):
        # Уцелевшие 2:0 — чистый перевес, и по ним одним вердикт был бы
        # «B лучше». Но выпало половина запрошенного, и выпало не случайно.
        self.assertEqual(bench.verdict(wins=2, losses=0, ties=0, unusable=2),
                         "судья не справился")

    def test_the_bar_is_counted_from_the_comparisons_asked_for(self):
        # 24 уцелевших из 36: перевес 6. От уцелевших 6/24 = 0.25 выше порога
        # 1/√24 = 0.20 — победа. От запрошенных 6/36 = 0.17 ровно на пороге
        # 1/√36 = 0.17 — той победы не было, её сделало выпадение.
        self.assertEqual(bench.verdict(wins=15, losses=9, ties=0, unusable=12),
                         "не отличить")

    def test_a_dropout_at_the_limit_still_yields_a_verdict(self):
        # Ровно треть — ещё не «не справился»: иначе ограда съедает годные
        # прогоны и стенд молчит всегда.
        self.assertEqual(bench.verdict(wins=5, losses=1, ties=0, unusable=3),
                         "B лучше")

    def test_dropouts_alone_are_not_nothing_to_compare(self):
        # «Нечего сравнивать» — это когда сравнений не просили. Когда их
        # просили и все потеряли, это провал судьи, и звать его надо так.
        self.assertEqual(bench.verdict(wins=0, losses=0, ties=0, unusable=4),
                         "судья не справился")


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

    def test_a_reach_for_tools_is_not_a_tie_even_when_it_says_the_word(self):
        # Ровно случай из первого платного прогона: судья пошёл сверяться с
        # файлами, а слово «ничья» попало в тот же текст и ушло в счёт ничьёй
        # — то есть выпавшее сравнение записалось доказательством сходства.
        said = ("I'll verify both answers against the actual files.\n"
                '<invoke name="Bash">\n'
                '<parameter name="command">ls -la</parameter>\n'
                "а пока, пожалуй, ничья")
        picked, why = bench.read_pick(said, self.LABELS)
        self.assertIsNone(picked)
        self.assertIn("инструмент", why)

    def test_a_reach_for_tools_naming_a_label_is_not_a_choice(self):
        # Метка внутри плана проверки — не выбор: судья её ещё не сделал.
        said = 'Сначала проверю A1f2: <invoke name="Read">src/a.ts</invoke>'
        self.assertIsNone(bench.read_pick(said, self.LABELS)[0])

    def test_a_plain_verdict_that_merely_mentions_code_still_counts(self):
        # Ограда ловит синтаксис вызова, а не разговор о файлах: ответ со
        # словом «Bash» или с путём — обычный вердикт.
        self.assertEqual(bench.read_pick("B9ab: он цитирует src/a.ts:12, не Bash",
                                         self.LABELS)[0], "pe")


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
        # Сравнения просили и все потеряли — это провал судейства, а не
        # пустой прогон: «нечего сравнивать» прозвучало бы как «не о чем».
        self.assertIn("судья не справился", out)
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

    def test_a_judge_that_reaches_for_tools_kills_the_verdict_not_just_the_pair(self):
        # Три случая, два длинных: судья тянется к инструментам ровно там, где
        # варианты и различались, и отвечает чисто на коротком. По уцелевшему
        # короткому base выигрывает 2:0 — и это ровно тот вердикт, которого
        # быть не должно: выпало две трети запрошенного.
        self._results([
            self._rec("base", "c1", "ХОРОШИЙ короткий разбор"),
            self._rec("pe", "c1", "догадка"),
            self._rec("base", "c2", "разбор", prompt="ДЛИННЫЙ разбери c2"),
            self._rec("pe", "c2", "ХОРОШИЙ разбор", prompt="ДЛИННЫЙ разбери c2"),
            self._rec("base", "c3", "разбор", prompt="ДЛИННЫЙ разбери c3"),
            self._rec("pe", "c3", "ХОРОШИЙ разбор", prompt="ДЛИННЫЙ разбери c3"),
        ])
        self._only_on_path(FAKE_JUDGE_REACHES)
        rc, out = self._judge()
        self.assertEqual(rc, 0)
        rows = self._verdicts()
        self.assertEqual(len(rows), 6, "судили не все пары")
        dropped = [v for v in rows if v["case"] in ("c2", "c3")]
        self.assertEqual([(v["picked"], v["tie"]) for v in dropped],
                         [(None, False)] * 4, "тяга к инструментам засчитана ничьёй")
        self.assertIn("ничьих 0", out)
        self.assertIn("судья не ответил в 4 сравнениях из 6", out)
        self.assertIn("вердикт: судья не справился", out)

    def test_a_sweep_among_the_survivors_is_not_a_verdict(self):
        # Здесь выпадения негодны и по старому счёту тоже: единственное, что
        # меняется, — от чего считается планка. Уцелело два сравнения, base
        # взял оба; по двум это «A лучше», по шести запрошенным — вердикта нет.
        self._results([
            self._rec("base", "c1", "ХОРОШИЙ короткий разбор"),
            self._rec("pe", "c1", "догадка"),
            self._rec("base", "c2", "разбор", prompt="ДЛИННЫЙ разбери c2"),
            self._rec("pe", "c2", "ХОРОШИЙ разбор", prompt="ДЛИННЫЙ разбери c2"),
            self._rec("base", "c3", "разбор", prompt="ДЛИННЫЙ разбери c3"),
            self._rec("pe", "c3", "ХОРОШИЙ разбор", prompt="ДЛИННЫЙ разбери c3"),
        ])
        self._only_on_path(FAKE_JUDGE_MUTE_ON_LONG)
        rc, out = self._judge()
        self.assertEqual(rc, 0)
        self.assertEqual([(v["picked"], v["tie"]) for v in self._verdicts()
                          if v["case"] != "c1"], [(None, False)] * 4)
        self.assertIn("base выиграл 2", out)
        self.assertIn("вердикт: судья не справился", out)

    def test_the_judge_is_told_it_has_no_tools(self):
        # Ограда судье руки отняла, но модели об этом никто не сказал, и она
        # тратила ответ на попытку сверки. Проверяется промпт, ДОШЕДШИЙ до
        # ребёнка, а не константа в модуле.
        self._results([self._rec("base", "c1", "а"), self._rec("pe", "c1", "б")])
        self._only_on_path(FAKE_JUDGE)
        calls = os.path.join(self.tmp, "calls.jsonl")
        self.addCleanup(os.environ.pop, "CCKIT_TEST_CALLS", None)
        os.environ["CCKIT_TEST_CALLS"] = calls
        self._judge()
        with open(calls, encoding="utf-8") as fh:
            asked = [json.loads(l) for l in fh if l.strip()]
        self.assertTrue(asked)
        for call in asked:
            q = call["prompt"]
            self.assertIn("нет инструментов", q, "судье не сказали, что рук нет")
            self.assertIn("ровно одна метка", q, "судье не сказали, что ответ — метка")

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
