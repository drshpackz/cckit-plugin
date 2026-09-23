# Группа `mcp` выдаёт ВСЕ MCP-серверы машины разом; 13 инструментов моста, включая `send_reply`, не названы ни в CAPS, ни в NEVER

**Статус:** измерено (по коду; живой прогон не делался — нет Bash и бюджета)
**Где:** bin/cckit_assistant.py:83,89; bin/cckit_core.py:47-48; ~/.cckit/current/mcp/src/server.ts:37-458
**Класс:** проверка (ограда, которую не спрашивают) + среда

## Как воспроизвести

Инструменты, которые объявляет `~/.cckit/current/mcp/src/server.ts`
(`server.registerTool(...)`, 13 штук):

```
list_sessions pulse get_progress read_messages send_reply list_files read_file
read_since_prompt search_files git_read usage_cost list_subagents read_subagent
```

В Claude Code они видны как `mcp__<сервер>__<имя>`. Grep по плагину
(`mcp__|send_reply|read_since_prompt` вне `docs/`): **0 совпадений**.
`CAPS["mcp"] = []` — «not a tool list: controls --strict-mcp-config».

Механика ограды (`cckit_core.py:47`): флаг `--strict-mcp-config` ставится,
только если `strict_mcp` истинно, то есть пока `mcp` **не выдан**. Без флага
ребёнок берёт `mcpServers` из `~/.claude.json` владельца и `.mcp.json`
проекта — **все**, не один. `--mcp-config` ядро не передаёт никогда.

Значит выдать `mcp` = выдать каждый MCP-сервер, зарегистрированный у
владельца машины, целиком, и ни одно `mcp__*` имя не попадает в
`--disallowedTools`. Из 13 инструментов моста 12 читают, а `send_reply`
(server.ts:181) **пишет в живую сессию другого агента** — это ровно та
способность, которую CAPS запирает под `peers` (`SendMessage`). Ассистент с
`mcp` и без `peers` получает `SendMessage` под вторым именем. Тот же класс,
что `Bash`/`Monitor` и `Agent`/`Task`: одна способность, два имени, названо
одно.

## Чем доказано

`tests/test_fence.py:175-178` утверждает лишь `CAPS["mcp"] == []`. Ни один
тест не утверждает, что при выданном `mcp` в `disallowed` есть хоть одно
`mcp__` имя, — потому что их там и нет. Тест, красный на `HEAD`:

```python
def test_granting_mcp_does_not_open_peers_by_another_name(self):
    off = ck.caps_to_disallowed(set(ck.BASE_CAPS) | {"mcp"})
    self.assertTrue(any(t.startswith("mcp__") and t.endswith("__send_reply") for t in off),
                    "выдан mcp без peers, а send_reply моста не запрещён: %r" % off)
```

На `HEAD` `off` не содержит ни одного `mcp__`, тест падает с этим списком.

Число: 13 объявленных, 0 названных, 1 пишущий (`readOnlyHint: false`).

## Что предлагаю

Не список имён моста (он состарится, как CAPS), а **свойство**: выданный
`mcp` — это выданный **перечень серверов**, а не флаг. В `card.yaml` —
`mcp: [имя-сервера, ...]`; ядро передаёт `--strict-mcp-config` **всегда** и
`--mcp-config <файл>` с ровно этими серверами, файл собирается в доме
экземпляра из `~/.claude.json`. Тогда «в неизвестном сервере ничего не
запрещено» превращается в «неизвестный сервер не подключён». Для моста
дополнительно: `send_reply` — в `peers`, как `SendMessage`, по имени
`mcp__<сервер>__send_reply`, чтобы `peers` запирал обе двери.

## Чего это НЕ закрывает

- Зарегистрирован ли мост в `~/.claude.json` этой машины — **не проверено**
  (`~/.claude` мне закрыт). Если нет, дыра пуста сегодня и откроется первой
  же регистрацией; свойство от этого не меняется.
- Не читал вызов `launch_argv` в установщике: что `strict_mcp = "mcp" not in
  granted` — из комментария и теста, не из строки вызова.
- Снимает ли `--strict-mcp-config` серверы, привезённые **плагинами** (их
  `.mcp.json`), — гипотеза; если нет, ограда без `mcp` тоже не полна.
- Живой прогон «ассистент с `mcp` зовёт `send_reply`» не делался. Предикат
  показан, последствие — нет.
