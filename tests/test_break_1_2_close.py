"""Взлом закрытия 1.2: где новые проверки зеленеют впустую.

Каждый тест здесь КРАСНЫЙ на дереве, где 1.2 объявлена закрытой, и назван по
дыре, а не по функции. Рабочий код не правился.

1. `lint-learned` узнаёт LEARNED.md по имени с точностью до регистра, а macOS
   (APFS по умолчанию) — нет. `learned.md` — тот же файл. Живой прогон
   2026-09-24 (haiku, `-p`, bypassPermissions, одноразовый дом в scratch):
   Read+Write `<дом>/learned.md` положили запись без статуса в LEARNED.md на
   диске, отказа не было. Контроль в том же доме, n=2: Edit `LEARNED.md` с той
   же записью — отказ хука, файл не изменился. Проба хуков просит правку
   только по точному имени, поэтому говорит «ок» при открытой двери.
   Харнесс, наоборот, сопоставляет правила без учёта регистра (тот же день:
   Write в `.claude/SETTINGS.json` и `.claude/AGENTS/t.md` — отказ ограды),
   так что дыра — в линтере, а не в ограде.

2. Правило владельца «deny shell» не закрывает выдачу `shell-subagents`:
   `grant spawn,shell-subagents` проходит молча, слова владельца не
   показываются, `Bash` уходит в allow. Выдача сама названа опасной ровно
   потому, что это шелл.
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "bin"))

from harness import Sandbox  # noqa: E402
import test_hooks as th  # noqa: E402
import test_home_fence as hf  # noqa: E402


def case_insensitive(d):
    """Один ли файл `X` и `x` в этом каталоге — так на APFS по умолчанию."""
    probe = os.path.join(d, "CaseProbe.tmp")
    open(probe, "w").close()
    try:
        return os.path.exists(os.path.join(d, "caseprobe.tmp"))
    finally:
        os.remove(probe)


@unittest.skipIf(sys.platform == "win32", "полиглот на windows проверяется отдельно")
class TestLintLearnedSeesTheSameFileUnderAnotherCase(unittest.TestCase):
    def _home(self, sb):
        _, home = th.install(sb, ["hooks: [lint-learned]"])
        if not case_insensitive(home):
            self.skipTest("ФС различает регистр: learned.md — другой файл")
        with open(os.path.join(home, "LEARNED.md"), "w", encoding="utf-8") as fh:
            fh.write(th.CLEAN)
        return home

    def _decision(self, home, tool, ti):
        proc = th.fire(home, "PreToolUse", "lint-learned",
                       {"hook_event_name": "PreToolUse", "tool_name": tool,
                        "cwd": home, "tool_input": ti})
        h = (th.out_json(proc) or {}).get("hookSpecificOutput") or {}
        return h.get("permissionDecision")

    def test_write_to_lowercase_name_is_refused_like_the_real_name(self):
        with Sandbox() as sb:
            home = self._home(sb)
            got = (self._decision(home, "Write", {
                       "file_path": os.path.join(home, "LEARNED.md"),
                       "content": th.DIRTY}),
                   self._decision(home, "Write", {
                       "file_path": os.path.join(home, "learned.md"),
                       "content": th.DIRTY}))
            self.assertEqual(
                got, ("deny", "deny"),
                "Write в learned.md — это запись в LEARNED.md на этой ФС, а "
                "линтер её пропустил (решение: %r). Живьём под bypass запись "
                "без статуса легла на диск." % (got[1],))

    def test_bash_append_to_lowercase_name_is_refused(self):
        # Эвристика по Bash признана неполной, но регистр в её списке обходов
        # не назван, а это самый дешёвый обход: у субагента с shell-subagents
        # хватает `echo >>`, и ограда путей его не держит — learned.md не
        # запрещён ничем.
        with Sandbox() as sb:
            home = self._home(sb)
            got = self._decision(home, "Bash", {
                "command": "printf '\\n## Без статуса\\n\\nтекст\\n' >> learned.md"})
            self.assertEqual(got, "deny",
                             "`>> learned.md` пишет в LEARNED.md мимо линтера: "
                             "и обёртка (case *LEARNED.md*), и регулярка "
                             "сравнивают регистр")


class TestOwnerRuleOnShellCoversShellForSubagents(unittest.TestCase):
    def test_grant_shell_subagents_after_owner_denied_shell_is_refused(self):
        words = "шелла этому ассистенту не давать"
        with Sandbox() as sb:
            home, name = hf.seed_and_install(sb)
            rc0, out0 = hf.call(["owner-rule", name, "deny", "shell", words])
            self.assertEqual(rc0, 0, out0)
            rc, out = hf.call(["grant", name, "spawn,shell-subagents", "--i-mean-it"])
            with open(os.path.join(home, ".claude", "settings.json"),
                      encoding="utf-8") as fh:
                allow = json.load(fh)["permissions"]["allow"]
            self.assertEqual(
                (rc, words in out, "Bash" in allow), (3, True, False),
                "владелец закрыл shell своими словами, а выдача shell-subagents "
                "прошла молча и положила Bash в allow: %s" % out.strip()[-200:])


if __name__ == "__main__":
    unittest.main()
