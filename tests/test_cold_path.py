# Путь чужого человека: от чистой установки до полезного результата, без единого
# нашего инструмента.
#
# Этот файл существует потому, что плагин целый вечер умел поставить ассистента,
# осмотреть, выдать права и снести — и не умел дать ему работу. Дыра прожила
# день сквозь 190 тестов, взломщика и живые пробы: задания раздавались личным
# CLI владельца машины, и путь «поставил → поручил» ни разу не проходился
# целиком.
#
# Проверяется не «работает ли функция», а «есть ли глагол».
import io
import re
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402

PLUGIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ROLE = os.path.join(PLUGIN, "assistants", "design-scout", "ROLE.md")


def call(argv):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        try:
            rc = ck.main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue()


PROMISE_FILES = ["README.md"] + [
    os.path.join("skills", d, "SKILL.md")
    for d in sorted(os.listdir(os.path.join(PLUGIN, "skills")))
]
# Две формы, обе законные: «cckit assistant <глагол>» в прозе и «$CK <глагол>»
# в примерах README. Вторая появилась потому, что бинарника `cckit` плагин не
# везёт, — и сканер, знающий только первую, объявлял бы обещание отсутствующим.
VERB = re.compile(r"(?:cckit assistant|\$CK) ([a-z][a-z-]+)")


def promised_verbs():
    """Глаголы, которые продукт обещает — из README и скиллов, а не из списка,
    напечатанного руками.

    Прежняя версия перебирала ("install", "run", "list", "reset") — то есть
    ОПЯТЬ список, и следующий пропущенный глагол она бы не поймала по той же
    причине, по которой никто не поймал отсутствие `run`. Сторож, растущий
    вместе с обещаниями, сходится: пообещал в README — получил проверку.
    """
    found = {}
    for rel in PROMISE_FILES:
        path = os.path.join(PLUGIN, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for verb in VERB.findall(fh.read()):
                found.setdefault(verb, []).append(rel)
    return found


def cli_verbs():
    """Глаголы, которые CLI печатает в собственной справке."""
    _, out = call([])
    return set(VERB.findall(out))


class TestPromisesAndVerbs(unittest.TestCase):
    def test_every_verb_the_product_promises_exists_in_the_cli(self):
        cli = cli_verbs()
        missing = {v: where for v, where in promised_verbs().items() if v not in cli}
        self.assertEqual(missing, {},
                         "обещано в документации, но в CLI нет: %r" % (missing,))

    def test_every_verb_the_cli_offers_is_promised_somewhere(self):
        # Обратная сторона: команда, о которой нигде не написано, человеку не
        # найдётся. Это не так страшно, как отсутствующая, но это тоже разрыв
        # между тем, что есть, и тем, что обещано.
        promised = set(promised_verbs())
        orphan = sorted(v for v in cli_verbs() if v not in promised)
        self.assertEqual(orphan, [],
                         "есть в CLI, но нигде не обещано: %s" % orphan)

    def test_the_promise_scan_actually_finds_something(self):
        # Регулярное выражение, переставшее совпадать, обнулило бы обе проверки
        # молча — и они остались бы зелёными навсегда.
        self.assertGreaterEqual(len(promised_verbs()), 4,
                                "сканер обещаний ничего не нашёл — он сломан")


class TestColdPath(unittest.TestCase):
    """Установка → список → поручение → снос, целиком в песочнице."""

    def test_a_stranger_can_install_then_give_work_then_remove(self):
        with Sandbox() as sb:
            with open(ROLE, encoding="utf-8") as fh:
                body = fh.read()
            body = body.replace("{PROJECT}", sb.project).strip()
            sb.set_reply("готово", transcript_prompt=body)

            rc, out = call(["install", "design-scout", "--project", sb.project])
            # Роль обязана НАЙТИСЬ в поставке плагина: у чужого человека своей
            # библиотеки нет, и раньше здесь было «нет карточки».
            self.assertNotIn("нет карточки", out)
            self.assertNotIn("не найдена", out)
            # Дальше поддельный ребёнок пройти не может по построению: проба
            # ограды смотрит на ДИСК, а подделка ничего не пишет. Проверяем,
            # что дошли до проб, — это и есть граница возможного без модели.
            self.assertIn("проба ограды", out)
            home = os.path.join(sb.home, ".cckit", "assistants",
                                "design-scout@" + os.path.basename(sb.project))
            self.assertTrue(os.path.isfile(os.path.join(home, "launch.json")),
                            "дом не собран:\n" + out)
            # Хуки у чужого человека включаются карточкой из поставки, а не
            # руками: дом обязан прийти с ними, и проба обязана их ПРОБОВАТЬ.
            # «не объявлены» здесь — это 1.2 без включения: механизм есть,
            # дом не действует сам.
            self.assertIn("проба хуков", out)
            self.assertNotIn("не объявлены", out,
                             "поставляемая роль приехала без хуков:\n" + out)
            self.assertEqual(ck.installed_hooks(home),
                             ["lint-learned", "read-ledger", "report-done"], out)

            rc, out = call(["list", "--all"])
            self.assertEqual(rc, 0, out)
            self.assertIn("design-scout", out)

            sb.set_reply("две строки ответа")
            rc, out = call(["run", "design-scout@" + os.path.basename(sb.project),
                            "назови файл со строкой"])
            self.assertEqual(rc, 0, "поручить работу не удалось:\n" + out)
            self.assertIn("две строки ответа", out)

            rc, out = call(["reset", "design-scout@" + os.path.basename(sb.project)])
            # reset тоже ищет роль — и тоже искал её ровно в одном месте, где у
            # чужого человека пусто. Здесь проверяется, что роль НАЙДЕНА и дом
            # пересобран; ненулевой код — это честный отказ проб заверить то,
            # чего они не смогли проверить поддельным ребёнком.
            self.assertNotIn("нет карточки", out)
            self.assertIn("пересобрано из роли", out)
            self.assertIn("LEARNED.md", out, "память не названа сохранённой")


if __name__ == "__main__":
    unittest.main()
