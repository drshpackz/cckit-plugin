# README: «библиотека держит одну роль». Плагин везёт две, вторая не названа нигде

**Статус:** измерено (счёт вхождений по всему дереву, .git исключён отдельно)
**Где:** README.md:119-120 · assistants/cckit-smith/ (везётся) · bin/cckit_assistant.py:575
**Класс:** обещание (существует и нигде не обещано)

## Как воспроизвести

README, раздел «Known limits»:

> - The library holds one role. `find-agent` will honestly tell you there is
>   nothing to install.

Откуда берутся роли (bin/cckit_assistant.py:571-575):

```python
def role_roots():
    return [("ваша библиотека", library_dir()),
            ("роли плагина", os.path.join(plugin_dir(), "assistants"))]
```

`assistants/` плагина содержит **две** роли с `card.yaml`:
`assistants/design-scout/` и `assistants/cckit-smith/`.

Вторая отслеживается git — значит едет к каждому, кто поставит плагин:

```
rg -c 'cckit-smith' .git/index
3
```

Сколько раз `cckit-smith` упомянута во всём дереве вне `.git`:

```
rg -n 'cckit-smith' --glob '!.git/**' .
assistants/cckit-smith/card.yaml:1:name: cckit-smith
```

**Одно вхождение, и то — собственная карточка.** Ноль в README, ноль в
`skills/**`, ноль в `tests/**`, ноль в `RELEASE-NOTES.md`. Для сравнения,
`design-scout` встречается в 9 файлах вне `.git` (README, четыре теста, планы,
карточка).

То есть: плагин публикует роль, которая (а) противоречит написанному в README
ограничению, (б) не покрыта ни одним тестом, (в) не названа ни одним скиллом,
и (г) невидима в CLI вовсе — см.
`2026-09-24-net-glagola-kotoryy-pokazhet-roli.md`. Единственный способ узнать
о ней — попросить несуществующую роль и прочитать список в тексте отказа.

Содержимое карточки (`assistants/cckit-smith/card.yaml`) описывает роль,
которая улучшает **сам CCKit**: `writes: ["docs/findings/**",
"docs/superpowers/specs/**"]`, `budget_usd: 3.00`, `model: claude-opus-5`.
Установленная в чужой проект, она будет писать в `docs/findings/` чужого
репозитория.

## Чем доказано

Мутацию не прогонял — в ограде нет Bash. Доказательство — счёт по всему
дереву: `rg -n 'cckit-smith' --glob '!.git/**'` даёт ровно одну строку, а
`.git/index` содержит имя, то есть файлы отслеживаются и попадут в поставку.
Оба числа перепроверяются одной командой каждое.

Тест, красный на `HEAD`, — свойство «каждая везомая роль названа в
документации»:

```python
def test_every_shipped_role_is_documented(self):
    roles = sorted(d for d in os.listdir(os.path.join(PLUGIN, "assistants"))
                   if os.path.isfile(os.path.join(PLUGIN, "assistants", d, "card.yaml")))
    self.assertTrue(roles, "сканер ролей ничего не нашёл — он сломан")
    text = "".join(open(os.path.join(PLUGIN, rel), encoding="utf-8").read()
                   for rel in PROMISE_FILES if os.path.isfile(os.path.join(PLUGIN, rel)))
    silent = [r for r in roles if r not in text]
    self.assertEqual(silent, [], "плагин везёт роль, о которой нигде не сказано: %s" % silent)
```

На `HEAD` падает: `silent == ['cckit-smith']` (в README и `skills/**` строки
`cckit-smith` нет — измерено выше). Прогон:
`python3 -m unittest tests.test_cold_path`.

## Что предлагаю

Решение принимает владелец, потому что вариантов два и они противоположны:

1. **Роль служебная, чужому не нужна** — тогда её не место в `assistants/`,
   которую `role_roots()` объявляет библиотекой плагина. Перенести в
   `dev/roles/cckit-smith/` (или в `.gitignore`), и README остаётся верным
   буквально.
2. **Роль публичная** — тогда правится README: «The library holds two roles»,
   и `cckit-smith` получает строку в разделе про роли и хотя бы одно
   упоминание в `skills/find-agent/SKILL.md`. Плюс тест выше — чтобы третья
   роль не приехала молча.

В обоих случаях тест ставится сразу: он проверяет **свойство** («везём =
обещаем»), а не конкретное имя, и переживёт любое из двух решений.

## Чего это НЕ закрывает

- Я не проверял, что `cckit-smith/ROLE.md` **переносима** — то есть что в ней
  нет путей вида `/Users/...` и что `{PROJECT}`/`{HOME}` расставлены так, как
  требует `skills/find-agent/SKILL.md:43`. Ворота `dev.sh:136` ловят только
  `$HOME` того, кто собирает, — на чужой машине этот путь другой.
- Я не смотрел, что именно делает `find-agent`, когда ролей две: фраза «will
  honestly tell you there is nothing to install» относится к поведению
  модели, читающей скилл, а не к коду, и проверяется только прогоном
  `dev.sh eval` (деньги и сеть — без задания не запускал).
- Число «9 файлов для design-scout» — из `rg -l`, включая `docs/` и
  `LEARNED.md`; как обещание считается только README и `skills/**`.
