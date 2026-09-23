# README учит работать командой `cckit`, которой плагин не привозит

**Статус:** измерено (счёт строк, не прогон — у меня нет Bash, см. «Чем доказано»)
**Где:** README.md:41-52, README.md:60-62 · bin/ (нет исполняемого `cckit`)
**Класс:** обещание + дорога в обход

## Как воспроизвести

Все командные строки README:

```
rg -n 'python3|PLUGIN_ROOT|\bcckit\b' README.md
11:/plugin marketplace add drshpackz/cckit-plugin
12:/plugin install cckit@cckit-plugin
15:Then, in any session: `/cckit:create-agent`, `/cckit:list-agents`,
16:`/cckit:find-agent`.
42:cckit assistant install design-scout --project . --also-read ../other-tree
43:cckit assistant run design-scout@myrepo "какой настройкой задаётся X, дай path:line"
48:`cckit assistant list`, `cckit assistant tree`, `cckit assistant show <id>` and
49:`cckit assistant where <id>`; change what it may do with
50:`cckit assistant grant` and `cckit assistant revoke`, and pin a decision of
52:`cckit assistant owner-rule`, which outranks the agent.
61:cckit-bench run   --cases cases.json --project . --variant a=old.md --variant b=new.md
62:cckit-bench judge --run <dir> --a a --b b --project .
82:`LEARNED.md` and its memory, and survives `cckit assistant reset`, which
```

Числа: **11 командных строк** в README зовут `cckit` / `cckit-bench`.
**0 вхождений** `python3` и **0** `CLAUDE_PLUGIN_ROOT` во всём README.

Что везёт плагин (`ls bin/`): `cckit_assistant.py`, `cckit_bench.py`,
`cckit_core.py`, `cckit_learned.py`. Исполняемого файла `cckit` или
`cckit-bench` в поставке нет; ничто в плагине не кладёт их на PATH — ни
`hooks/session-start` (он только печатает текст скилла), ни `dev.sh`
(`reinstall` зовёт `claude plugin install`, и только).

`cckit` есть у владельца машины — `~/.cckit/current/bin/`, дерево, которое
устанавливается отдельно от плагина и в маркетплейсе не упоминается
(`.claude-plugin/marketplace.json` везёт один плагин `cckit`, `source: "./"`).

Итог для чужого человека, прошедшего ровно README: после
`/plugin install cckit@cckit-plugin` раздел «Giving it work» —
единственное место, где сказано, **как дать ассистенту работу**, — состоит
целиком из команд, которых у него в оболочке нет. `command not found: cckit`.

Скиллы эту дыру знают и чинят наполовину: `skills/list-agents/SKILL.md:9`,
`skills/find-agent/SKILL.md:32`, `skills/create-agent/SKILL.md:10,44` дают
форму `python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py"` с оговоркой
«короче, если установлен CCKit CLI». README — лицо продукта на GitHub, куда
человек смотрит **до** установки, — этой оговорки не содержит ни разу.

## Чем доказано

Мутацию прогнать не могу: в моей ограде нет Bash, только чтение и grep.
Поэтому доказываю предикатом, который считается по тексту, и даю ведущей
сессии тест, красный на `HEAD` по построению.

Существующие ворота — `tests/test_cold_path.py:41` — ловят **глагол**:

```python
VERB = re.compile(r"cckit assistant ([a-z][a-z-]+)")
```

То есть сверяют множество глаголов в README и скиллах с множеством глаголов в
справке CLI. Обе стороны совпадают, и оба теста зелены. Форма вызова в
регулярное выражение не входит вовсе: ворота не различают «команда `cckit`
существует» и «команда `cckit` существует у автора». Ровно тот же зазор, что
однажды спрятал отсутствие `run`, — только на уровень выше: глагол есть,
исполняемого файла нет.

Тест, который обязан упасть на `git show HEAD:README.md` (число вхождений
`python3` в README = 0, а требуется ≥ 1 на каждый блок кода с `cckit`):

```python
def test_readme_shows_a_form_a_stranger_can_actually_type(self):
    # У чужого человека нет `cckit` на PATH: плагин его не кладёт.
    text = open(os.path.join(PLUGIN, "README.md"), encoding="utf-8").read()
    blocks = re.findall(r"```\n(.*?)```", text, re.S)
    cckit_blocks = [b for b in blocks if re.search(r"^cckit[- ]", b, re.M)]
    self.assertTrue(cckit_blocks, "сканер блоков сломан")
    naked = [b for b in cckit_blocks if "cckit_assistant.py" not in b
             and "cckit_bench.py" not in b]
    self.assertEqual(naked, [], "в README есть блок команд, который нельзя "
                                "набрать без личного CLI автора: %r" % naked)
```

На `HEAD` `naked` — оба блока (строки 41-44 и 60-63), тест красный с
сообщением, называющим их дословно. Прогон: `python3 -m unittest
tests.test_cold_path -k readme`.

## Что предлагаю

1. В README оба блока — в форме, которую можно набрать сразу после установки
   плагина, а личный CLI — как сокращение, а не как основу:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py" install design-scout --project .
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py" run design-scout@myrepo "..."
# короче, если поставлен CCKit CLI: cckit assistant install ... / cckit assistant run ...
```

   Так же в блоке стенда: `python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_bench.py" run ...`.

2. Тест выше — в `tests/test_cold_path.py`, рядом с двумя проверками глаголов.
   Чиним **свойство** («обещанную команду можно набрать после чистой
   установки»), а не два конкретных блока: любой новый блок с `cckit` в README
   уронит его сам.

Почему не наоборот (не «положить `cckit` на PATH при установке плагина»):
плагин по правилу репозитория ничего не пишет за пределами `~/.cckit/`, а
класть исполняемые файлы на PATH из плагина — отдельное решение с отдельной
ценой. README дешевле и честнее.

## Чего это НЕ закрывает

- **Работает ли сама форма `${CLAUDE_PLUGIN_ROOT}`** внутри Bash-инструмента
  агента — отдельный вопрос, вынесен в
  `2026-09-24-forma-vyzova-v-skillah.md` (статус: гипотеза). Если переменная
  туда не приходит, предложенная правка меняет одну неработающую команду на
  другую.
- Человек, набирающий команды **в своём терминале**, а не через агента,
  `CLAUDE_PLUGIN_ROOT` не имеет в любом случае: ему нужен абсолютный путь до
  каталога плагина, и README его нигде не называет. Правка выше этого не
  решает.
- Число 11 — вхождения в README. Я не считал такие же строки в
  `docs/` и `RELEASE-NOTES.md`: `docs/` освобождён воротами нарочно
  (`dev.sh:133`), `RELEASE-NOTES.md` я не смотрел.
