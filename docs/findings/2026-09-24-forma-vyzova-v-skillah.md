# В скиллах строка `python3 "${CLAUDE_PLUGIN_ROOT}/…"` дана без глагола, а сама переменная не проверена

**Статус:** наблюдение (текст скиллов) + гипотеза (доходит ли переменная до Bash-инструмента)
**Где:** skills/list-agents/SKILL.md:8-14 · skills/find-agent/SKILL.md:31-34 · skills/create-agent/SKILL.md:44-45
**Класс:** дорога в обход + среда

## Как воспроизвести

`skills/list-agents/SKILL.md`, блок целиком:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py"
# короче, если установлен CCKit CLI: cckit assistant list          # this project (add --all for every project)
cckit assistant tree          # who created whom, with what capabilities
cckit assistant show <name>   # one instance in full
cckit assistant where <name> --path
```

Первая строка — без подкоманды: набранная как есть, она печатает справку и
возвращает 2. Дальше три строки в форме `cckit assistant …`, которой у
человека без личного CLI нет (см.
`2026-09-24-readme-zovet-binarnik-kotorogo-net.md`). Соответствие
«`cckit assistant X` → `python3 …/cckit_assistant.py X`» нигде не написано —
агент должен его додумать. То же в `find-agent:31-34` (строка без глагола,
следом `install <role> --project`) и в `create-agent:44-45`.

Вторая половина, гипотеза: `${CLAUDE_PLUGIN_ROOT}` — переменная **харнесса**.
Что известно точно: `hooks/hooks.json:9` полагается на неё для хуков, а
`dev.sh:124` выставляет её руками (`CLAUDE_PLUGIN_ROOT="$ROOT" bash …`) —
то есть в оболочке сама она не появляется. Доходит ли она до среды
Bash-инструмента, когда агент выполняет команду из скилла, я проверить не
могу: в моей ограде Bash нет. Если не доходит, строка раскрывается в
`python3 "/bin/cckit_assistant.py"` и падает с
`can't open file '/bin/cckit_assistant.py'` — то есть починка, закрывшая дыру
с отсутствующим `cckit`, не работает ни у кого.

Ни один тест этого не касается: `rg -n 'CLAUDE_PLUGIN_ROOT' tests/` — пусто
(вхождения есть только в `CLAUDE.md`, `skills/**`, `hooks/hooks.json`,
`dev.sh`, `bin/cckit_assistant.py:567`, `docs/`).

## Чем доказано

Доказана только текстовая половина — цитатами выше: строка без глагола и три
строки в форме, требующей личного CLI. Это наблюдение по трём файлам, не
предположение.

Половина про переменную — **гипотеза**, и я её так и помечаю. Решающая
проверка — одна команда в ведущей сессии, в сеансе с установленным плагином:

```
echo "root=[${CLAUDE_PLUGIN_ROOT:-ПУСТО}]"
```

Пусто → падает всё, что скиллы предлагают набирать; не пусто → остаётся
только текстовая половина находки. Опасного случая здесь не создаётся:
печатается предикат, а не последствие.

## Что предлагаю

1. Сделать блок самодостаточным — глагол в той же строке, в которой путь:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py" list     # this project (--all for every project)
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py" tree     # who created whom, with what capabilities
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py" show <name>
# короче, если поставлен CCKit CLI: cckit assistant list | tree | show <name> | where <name> --path
```

   Потолок слов у скиллов — 500 (`dev.sh:112`), кроме `using-assistants` (200);
   правка длиннее исходника на ~20 слов, в потолок укладывается.

2. Прежде чем менять три файла — прогнать `echo` выше. Если переменная
   пуста, правка другая: скиллам нужен путь, вычисляемый на месте, и это
   решение уровня продукта, а не редактуры.

## Чего это НЕ закрывает

- Не закрывает `using-assistants/SKILL.md:24` (`cckit assistant list`,
  без всякой оговорки) — он въезжает в **каждую** сессию через
  `hooks/session-start`, и там потолок 200 слов, так что альтернативную форму
  туда не вписать без выбрасывания чего-то другого. Отдельное решение.
- Не проверяет, что модель, прочитав исправленный блок, наберёт именно его:
  это меряется `dev.sh eval` (деньги и сеть), без задания не запускал.
- Гипотеза про переменную остаётся гипотезой до `echo`. Пока она не
  проверена, статус «починено» ни одной из трёх правок не положен.
