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


class TestTheVerbsExist(unittest.TestCase):
    """Глагол, которого нет в справке, человек не найдёт никогда."""

    def test_every_verb_a_stranger_needs_is_offered(self):
        rc, out = call([])
        for verb in ("install", "run", "list", "reset"):
            self.assertIn(verb, out, "в справке нет глагола «%s»" % verb)

    def test_the_help_shows_how_to_give_work_not_only_how_to_install(self):
        # Обвязка вокруг главного действия выглядит как работа. Здесь
        # проверяется само действие.
        _, out = call([])
        self.assertIn("run", out.split("\n")[0].lower() + out,
                      "справка не называет, чем ассистенту дают работу")


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
