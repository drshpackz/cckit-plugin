# Рука выученного слоя. Вопрос, ради которого она существует: стоит ли чего-то
# то, что ассистент накопил в LEARNED.md.
#
# Ломается это молча и двумя способами, оба дают одну и ту же строку «не
# отличить», и оба читаются как приговор выученному слою:
#
#  1. Мерить нечего. У свежей установки LEARNED.md НЕ пуст — установщик кладёт
#     туда шаблон на ~700 байт. Проверка «файл непустой» на нём срабатывает,
#     и стенд сравнивает две одинаковых руки, честно доложив «с выученным».
#  2. Мерить было что, но до модели оно не дошло. Выученный слой едет не
#     системным промптом, а @-импортом из CLAUDE.md песочницы; не доехал —
#     и обе руки опять одинаковы, а отчёт об этом не знает.
#
# Ни один тест здесь не запускает настоящий `claude`: те, которым нужен
# ребёнок, поднимают поддельного и ставят PATH РАВНЫМ одному каталогу с ним —
# при таком PATH настоящий недостижим в принципе, и промах стоит ошибки, а не
# денег. Живой LEARNED.md владельца только читается, никогда не меняется.
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import cckit_bench as bench  # noqa: E402
from cckit_assistant import LEARNED_MD  # noqa: E402

RECORD = """
## У этой сессии нет исполнения команд

**Статус: наблюдение** (2026-09-23, проба).

Доступный набор файловых инструментов, оболочки нет совсем.
"""

# Поддельный ребёнок. Он повторяет две вещи, измеренные на живой стенограмме
# 2026-09-23: карточка варианта приезжает как prompt_snapshot, а CLAUDE.md и
# его @-импорты — отдельной записью attachment.type == "instructions", где у
# каждого файла лежит его путь и всё содержимое.
FAKE_CHILD = r'''
import json, os, sys
state = os.environ["CCKIT_TEST_STATE"]
argv = sys.argv[1:]
calls = os.path.join(state, "calls.jsonl")
with open(calls, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
with open(calls, encoding="utf-8") as fh:
    sid = "s%d" % len([l for l in fh if l.strip()])

body = ""
card = os.path.join(os.getcwd(), ".claude", "agents", "v.md")
if os.path.exists(card):
    with open(card, encoding="utf-8") as fh:
        body = fh.read().split("---", 2)[-1].strip()
lines = [{"type": "attachment", "attachment": {
    "type": "prompt_snapshot", "systemPrompt": [body or "You are Claude Code"]}}]

if os.environ.get("CCKIT_TEST_IMPORTS") == "1":
    files = []
    for name in ("CLAUDE.md", "LEARNED.md"):
        f = os.path.join(os.getcwd(), name)
        if os.path.exists(f):
            with open(f, encoding="utf-8") as fh:
                files.append({"path": f, "type": "Project", "content": fh.read()})
    if files:
        lines.append({"type": "attachment",
                      "attachment": {"type": "instructions", "files": files}})

d = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "projects", "box")
os.makedirs(d, exist_ok=True)
with open(os.path.join(d, sid + ".jsonl"), "w", encoding="utf-8") as fh:
    for rec in lines:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
sys.stdout.write(json.dumps({"result": "ответ", "session_id": sid,
                             "total_cost_usd": 0.01}, ensure_ascii=False))
'''


class Tmp(unittest.TestCase):
    def tmpdir(self, prefix="cckit-mem-"):
        d = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def home_with(self, text):
        home = self.tmpdir()
        with open(os.path.join(home, "LEARNED.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return home


class TestNothingToMeasure(Tmp):
    def test_absent_learned_file_is_nothing_to_measure(self):
        self.assertIsNone(bench.copy_learned(self.tmpdir(), self.tmpdir()))

    def test_empty_learned_file_is_nothing_to_measure(self):
        self.assertIsNone(bench.copy_learned(self.home_with("   \n\n"), self.tmpdir()))

    def test_a_learned_file_is_copied_not_linked(self):
        # Каталог памяти, уводящий наружу дерева, CLI не читает.
        box = self.tmpdir()
        dest = bench.copy_learned(self.home_with("# что узнал\n\nизмерено: X\n"), box)
        self.assertTrue(os.path.isfile(dest))
        self.assertFalse(os.path.islink(dest))
        with open(dest, encoding="utf-8") as fh:
            self.assertIn("измерено", fh.read())

    def test_a_freshly_installed_learned_file_is_nothing_to_measure(self):
        # Главный тест этой руки. У свежей установки файл не пуст — в нём
        # шаблон установщика. Проверка «непустой» тут молча проходит, стенд
        # объявляет «с выученным» и сравнивает две одинаковых руки.
        self.assertIsNone(bench.copy_learned(self.home_with(LEARNED_MD), self.tmpdir()))

    def test_the_template_plus_one_record_is_something_to_measure(self):
        dest = bench.copy_learned(self.home_with(LEARNED_MD + RECORD), self.tmpdir())
        self.assertIsNotNone(dest)
        with open(dest, encoding="utf-8") as fh:
            copied = fh.read()
        # Копируется ВЕСЬ файл, включая шаблон: ассистент читает его целиком,
        # а вычитание шаблона — только способ понять, есть ли что мерить.
        self.assertEqual(copied, LEARNED_MD + RECORD)

    def test_a_symlinked_learned_file_is_copied_as_a_real_file(self):
        real = os.path.join(self.tmpdir(), "real.md")
        with open(real, "w", encoding="utf-8") as fh:
            fh.write(LEARNED_MD + RECORD)
        home, box = self.tmpdir(), self.tmpdir()
        os.symlink(real, os.path.join(home, "LEARNED.md"))
        dest = bench.copy_learned(home, box)
        self.assertFalse(os.path.islink(dest))
        with open(dest, encoding="utf-8") as fh:
            self.assertIn("оболочки нет совсем", fh.read())

    def test_a_live_learned_file_with_a_record_is_something_to_measure(self):
        # На настоящих файлах владельца, только чтение. Критерий здесь другой —
        # «есть заголовок записи» — и он ловит то, чего синтетика не ловит:
        # вычитание шаблона, съевшее вместе с ним и записи.
        found = []
        for p in sorted(glob.glob(os.path.expanduser(
                "~/.cckit/assistants/*/LEARNED.md"))):
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            if "\n## " in text:
                found.append(os.path.dirname(p))
        if not found:
            self.skipTest("на этой машине нет ассистента с записями в LEARNED.md")
        for home in found:
            self.assertIsNotNone(bench.copy_learned(home, self.tmpdir()),
                                 "%s: запись есть, а мерить якобы нечего" % home)


class TestNeedle(Tmp):
    def test_the_needle_comes_from_what_the_assistant_added(self):
        # Метка из шаблона нашлась бы в стенограмме любой установки, в том
        # числе той, где ассистент не узнал ничего.
        needle = bench.memory_needle(LEARNED_MD + RECORD)
        self.assertIn(needle, RECORD)
        self.assertNotIn(needle, LEARNED_MD)

    def test_the_needle_survives_json_encoding(self):
        # Стенограмма — JSONL: кавычка и обратная косая в ней не остаются
        # собой, и метка с ними никогда не найдётся.
        needle = bench.memory_needle(
            LEARNED_MD + '\n## Запись\n\nтут "кавычка" и \\ косая, а дальше'
            ' длинный кусок без них совсем\n')
        self.assertNotIn('"', needle)
        self.assertNotIn("\\", needle)

    def test_nothing_to_look_for_is_none(self):
        self.assertIsNone(bench.memory_needle(LEARNED_MD))


class TestDelivery(Tmp):
    """Выученное доехало до модели — или не доехало и мерить было нечего."""

    def transcript(self, lines):
        cfg = self.tmpdir()
        self.addCleanup(os.environ.__setitem__, "CLAUDE_CONFIG_DIR",
                        os.environ.get("CLAUDE_CONFIG_DIR", ""))
        os.environ["CLAUDE_CONFIG_DIR"] = cfg
        d = os.path.join(cfg, "projects", "box")
        os.makedirs(d)
        with open(os.path.join(d, "sid.jsonl"), "w", encoding="utf-8") as fh:
            for rec in lines:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def test_the_learned_layer_in_the_transcript_is_delivery(self):
        self.transcript([{"type": "attachment", "attachment": {
            "type": "instructions",
            "files": [{"path": "/box/LEARNED.md", "type": "Project",
                       "content": LEARNED_MD + RECORD}]}}])
        ok, note = bench.memory_delivered("sid", bench.memory_needle(LEARNED_MD + RECORD))
        self.assertTrue(ok, note)

    def test_the_learned_layer_missing_from_the_transcript_is_not_delivery(self):
        # Ровно тот провал, который выглядит как «выученный слой ничего не
        # даёт»: @-импорт не сработал, руки одинаковы, судья видит шум.
        self.transcript([{"type": "attachment", "attachment": {
            "type": "prompt_snapshot", "systemPrompt": ["тело роли"]}}])
        ok, note = bench.memory_delivered("sid", bench.memory_needle(LEARNED_MD + RECORD))
        self.assertFalse(ok)
        self.assertIn("выученн", note)

    def test_no_transcript_is_not_delivery(self):
        self.transcript([])
        self.assertFalse(bench.memory_delivered("нет-такой", "метка")[0])

    def test_a_run_whose_learned_layer_never_arrived_is_not_scorable(self):
        rec = {"variant": "learned", "case": "a", "ok": True, "prompt_ok": True,
               "memory_ok": False}
        self.assertFalse(bench.scorable(rec))

    def test_a_run_without_a_learned_layer_is_scored_as_before(self):
        rec = {"variant": "base", "case": "a", "ok": True, "prompt_ok": True}
        self.assertTrue(bench.scorable(rec))


class TestParseMemory(Tmp):
    VARIANTS = [{"name": "empty", "role_md": None}, {"name": "learned", "role_md": None}]

    def test_memory_for_an_unknown_variant_is_an_error(self):
        # Опечатка в имени иначе молчит: рука уходит в прогон без выученного
        # слоя, а отчёт сравнивает две одинаковых и называет это вердиктом.
        home = self.home_with(LEARNED_MD + RECORD)
        with self.assertRaises(ValueError) as e:
            bench.parse_memory(["learnd=" + home], self.VARIANTS)
        self.assertIn("learned", str(e.exception))

    def test_two_memories_for_one_variant_is_an_error(self):
        home = self.home_with(LEARNED_MD + RECORD)
        with self.assertRaises(ValueError):
            bench.parse_memory(["learned=" + home, "learned=" + home], self.VARIANTS)

    def test_a_home_that_does_not_exist_is_an_error(self):
        with self.assertRaises(ValueError):
            bench.parse_memory(["learned=" + os.path.join(self.tmpdir(), "нет")],
                               self.VARIANTS)

    def test_a_home_with_nothing_to_measure_is_refused_before_spending(self):
        # Свежая установка: прогон стоил бы денег и кончился бы строкой,
        # неотличимой от приговора выученному слою.
        with self.assertRaises(ValueError) as e:
            bench.parse_memory(["learned=" + self.home_with(LEARNED_MD)], self.VARIANTS)
        self.assertIn("нечего измерять", str(e.exception))

    def test_a_home_with_records_is_accepted(self):
        home = self.home_with(LEARNED_MD + RECORD)
        self.assertEqual(bench.parse_memory(["learned=" + home], self.VARIANTS),
                         {"learned": os.path.abspath(home)})


class TestRunVariantWithMemory(Tmp):
    """Сквозь run_variant, на поддельном ребёнке."""

    def setUp(self):
        self.tmp = self.tmpdir("cckit-mem-run-")
        self.run_dir = os.path.join(self.tmp, "run")
        self.project = os.path.join(self.tmp, "project")
        self.state = os.path.join(self.tmp, "state")
        for d in (self.run_dir, self.project, self.state):
            os.makedirs(d)
        for var in ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "PATH",
                    "CCKIT_TEST_STATE", "CCKIT_TEST_IMPORTS"):
            self.addCleanup(os.environ.__setitem__, var, os.environ.get(var, ""))
        os.environ["HOME"] = os.environ["USERPROFILE"] = self.tmp
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, ".claude")
        os.environ["CCKIT_TEST_STATE"] = self.state
        os.environ["CCKIT_TEST_IMPORTS"] = "1"
        binp = os.path.join(self.tmp, "bin")
        os.makedirs(binp)
        shim = os.path.join(binp, "claude")
        with open(shim, "w", encoding="utf-8") as fh:
            fh.write("#!" + sys.executable + "\n" + FAKE_CHILD)
        os.chmod(shim, 0o755)
        os.environ["PATH"] = binp          # настоящий claude недостижим
        self.role = os.path.join(self.tmp, "ROLE.md")
        with open(self.role, "w", encoding="utf-8") as fh:
            fh.write("Ты разведчик проекта {PROJECT}.\n")

    def calls(self):
        p = os.path.join(self.state, "calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def run_one(self, memory=None):
        variant = {"name": "learned", "role_md": self.role, "memory": memory}
        return bench.run_variant(variant, {"id": "c1", "prompt": "задание"},
                                 self.run_dir, self.project, "0.10")

    def test_the_learned_layer_is_placed_in_the_box_and_imported(self):
        rec = self.run_one(self.home_with(LEARNED_MD + RECORD))
        box = rec["sandbox"]
        with open(os.path.join(box, "LEARNED.md"), encoding="utf-8") as fh:
            self.assertIn("оболочки нет совсем", fh.read())
        with open(os.path.join(box, "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertIn("@LEARNED.md", fh.read())
        self.assertEqual(len(self.calls()), 1, "ребёнок не запускался — тест пуст")
        self.assertEqual([rec["memory"], rec["memory_ok"], bench.scorable(rec)],
                         ["с выученным", True, True])

    def test_a_learned_layer_that_never_arrived_is_not_a_measurement(self):
        os.environ["CCKIT_TEST_IMPORTS"] = "0"      # CLI не подхватил @-импорт
        rec = self.run_one(self.home_with(LEARNED_MD + RECORD))
        self.assertEqual(len(self.calls()), 1, "ребёнок не запускался — тест пуст")
        self.assertEqual([rec["ok"], rec["prompt_ok"], rec["memory_ok"],
                          bench.scorable(rec)], [True, True, False, False])

    def test_a_variant_without_memory_gets_no_learned_layer(self):
        rec = self.run_one(None)
        self.assertFalse(os.path.exists(os.path.join(rec["sandbox"], "LEARNED.md")))
        self.assertFalse(os.path.exists(os.path.join(rec["sandbox"], "CLAUDE.md")))
        self.assertEqual(len(self.calls()), 1, "ребёнок не запускался — тест пуст")
        self.assertEqual([rec["memory"], bench.scorable(rec)], ["без выученного", True])


if __name__ == "__main__":
    unittest.main()
