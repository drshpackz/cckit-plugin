# `cckit help` обещает `notify`, которого в `bin/` нет, и молчит про `assistant`, который есть

**Статус:** измерено (счёт по диску)
**Где:** ~/.cckit/current/bin/cckit:49,101-102,4; ~/.cckit/current/docs/TOOLS.md:17-20
**Класс:** обещание + среда

## Как воспроизвести

`cckit help` (строки 21-55) называет 24 команды. Диспетчер (81-104) знает
25: лишняя — `assistant|as` (102), в справке **не упомянута ни разу**.
Единственный глагол семьи, ведущий к плагину, невидим из её же справки.

Обратное: `cckit notify` (49) → `claude-chat-notify`. В `bin/` (68 файлов по
Glob) его нет; `command -v` не найдёт, `exec "$BIN/claude-chat-notify"` даст
`No such file`. TOOLS.md:17 честно пишет «пакет не берёт: claude-chat-notify»
— но справка `cckit` этой оговорки не содержит.

Сверх того в `bin/` лежат и не обещаны: `claude-tools`, `claude-cwd-wrapper`,
`claude-memory-guard`, `claude-memory-lint`. А TOOLS.md:18-20 называет
7 имён, которых в `bin/` нет (`claude-voice`, `-sing`, `-skeptic`,
`-briefing`, `-file-ledger`, `-file-watch`, `-autodriven`).

Среда: `cckit:4` — `/usr/projects/commons/TOOLS.md`; TOOLS.md:11-12 —
`/usr/projects/cckit-mcp`, `/root/projects/ccmonitor`; `config.ts:33` —
`/run/user/<uid>/cc-socks` (на macOS нет `/run/user`: реестр живых сессий
пуст без `CLAUDE_BRIDGE_SOCK_DIR`). Пути одной машины в поставке.

## Чем доказано

Проверка одна: множество глаголов в `help()` против множества в `case`, и
каждый `cmd=` против файла в `bin/`. Числа: 24 обещано, 25 принимается,
1 обещан без файла, 4 файла без обещания.

## Что предлагаю

В `help()` — строка `cckit assistant …  постоянный ассистент проекта  cckit-assistant`
рядом с «Сессии и соседи». `notify` — либо убрать из справки, либо в `case`
проверять `command -v` и падать с «не входит в пакет, см. TOOLS.md». И тест
в пакете (`cckit doctor`): каждый `cmd=` из диспетчера существует.

## Чего это НЕ закрывает

- Не проверял `cckit-inject` и `cckit-package` глубже диспетчера: их
  собственные `--help` против их кода не сверял.
- `docs/inject/CLI.md` и `docs/knowledge/` не читал (бюджет).
- Это семья, не плагин: `dev.sh check` сюда не дотягивается, и находка живёт
  только пока её кто-то помнит.
