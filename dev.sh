#!/usr/bin/env bash
# Development loop for the cckit plugin: check it, publish it, reinstall it.
#
# Exists so a fix never again has to wait on someone clicking through the
# Manage Plugins dialog — and so a fix cannot land in one copy and not another,
# which is how a security hole once stayed in the published plugin after being
# fixed locally.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKET="cckit-plugin"
PLUGIN="cckit"
ok=0

say()  { printf '%s\n' "$*"; }
good() { printf '  ok   %s\n' "$*"; }
bad()  { printf '  БЕДА %s\n' "$*"; ok=1; }

# Набор — самостоятельные ворота, а не хвост `check`: его гоняют по двадцать
# раз в час. В `check` он идёт ПЕРВЫМ: на красном наборе всё, что ниже, —
# шум, и читать его незачем.
cmd_test() {
    say "== набор =="
    local out n
    if out="$(cd "$ROOT" && python3 -m unittest discover -s tests 2>&1)"; then
        # «Ran 0 tests ... OK» — тоже успех для unittest: так выглядит набор,
        # который не нашёлся (переехал каталог, сломался импорт на уровне
        # модуля). Зелёные ворота на нуле тестов — ровно то, от чего ворота
        # заводили, поэтому число обязано быть названо и быть больше нуля.
        n="$(printf '%s\n' "$out" | sed -n 's/^Ran \([0-9][0-9]*\) test.*/\1/p' | tail -1)"
        if [ "${n:-0}" -gt 0 ] 2>/dev/null; then
            good "тесты — Ran $n tests"
            return 0
        fi
        bad "тесты — не нашлось ни одного теста: зелёное ничто"
        printf '%s\n' "$out" | tail -5 | sed 's|.*|    &|'
        return 1
    fi
    bad "тесты — набор красный:"
    # Хвост вывода — это стдаут соседних тестов, а не поломка: в прошлый раз
    # двадцать последних строк не содержали ни одного имени упавшего теста.
    # Показываем строки, которые называют упавшее; хвост — только если их нет.
    printf '%s\n' "$out" | grep -E '^(FAIL|ERROR):|^FAILED|^Ran ' | tail -20 | sed 's|.*|    &|' \
        || printf '%s\n' "$out" | tail -20 | sed 's|.*|    &|'
    return 1
}

# Срабатывание скиллов — единственное, чего юнит-тест не докажет: скилл,
# который не срабатывает, неотличим от несуществующего. Отдельной командой, а
# не внутри `check`, потому что стоит денег и ходит в сеть.
cmd_eval() {
    say "== срабатывание скиллов =="
    # Незапущенные ворота зелены. Без `claude` на PATH это молчаливый ноль,
    # поэтому проверка до запуска, а не после.
    if ! command -v claude >/dev/null 2>&1; then
        bad "claude не на PATH — случаи не запускались"
        return 1
    fi
    # Случаи — в evals/, по каталогу на случай. Флаги идут насквозь:
    # --case '<имя>', --runs N, --eval-dir evals-dispatcher (измерение
    # диспетчера, оно в ворота не входит — см. evals-dispatcher/README.md).
    # Первый прогон в непомеченном доверием каталоге спрашивает подтверждение:
    # отвечать человеку, --trust-plugin — для CI.
    ( cd "$ROOT" && claude plugin eval . --no-publish "$@" )
    local rc=$?
    if [ $rc -eq 0 ]; then
        good "скиллы срабатывают"
    else
        bad "скиллы — случаи красные (код $rc)"
    fi
    return $rc
}

cmd_check() {
    say "== проверка =="
    cmd_test
    for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json hooks/hooks.json; do
        python3 -c "import json;json.load(open('$ROOT/$f'))" 2>/dev/null \
            && good "$f" || bad "$f — не разбирается как JSON"
    done

    # Every .py that ships or tests, not one hand-picked file: the gate stayed
    # green once while the core next to it did not even parse.
    for f in "$ROOT"/bin/*.py "$ROOT"/tests/*.py; do
        [ -f "$f" ] || continue
        python3 -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())" "$f" 2>/dev/null \
            && good "${f#$ROOT/}" || bad "${f#$ROOT/} — синтаксис"
    done

    # Every skill needs name + a description that states only WHEN to use it.
    # A description that summarises the skill makes agents follow the summary
    # instead of reading the skill — a documented failure, not a style note.
    python3 - "$ROOT" <<'PY'
import glob, os, re, sys
root = sys.argv[1]
bad = 0
for f in sorted(glob.glob(os.path.join(root, "skills", "*", "SKILL.md"))):
    parts = open(f, encoding="utf-8").read().split("---")
    name = os.path.basename(os.path.dirname(f))
    if len(parts) < 3:
        print("  БЕДА %s — нет frontmatter" % name); bad = 1; continue
    head = parts[1]
    n = re.search(r"^name:\s*(\S+)", head, re.M)
    d = re.search(r"^description:\s*(.+)", head, re.M)
    if not n or not d:
        print("  БЕДА %s — нет name или description" % name); bad = 1; continue
    if n.group(1) != name:
        print("  БЕДА %s — name в frontmatter «%s» не совпадает с папкой" % (name, n.group(1))); bad = 1
    if not d.group(1).strip().startswith("Use when"):
        print("  БЕДА %s — description не начинается с «Use when»" % name); bad = 1
    words = len(open(f, encoding="utf-8").read().split())
    cap = 200 if name == "using-assistants" else 500
    if words > cap:
        print("  БЕДА %s — %d слов при потолке %d" % (name, words, cap)); bad = 1
    else:
        print("  ok   %s (%d слов)" % (name, words))
sys.exit(bad)
PY
    [ $? -ne 0 ] && ok=1

    bash -n "$ROOT/hooks/session-start" && good "hooks/session-start" || bad "hooks/session-start"
    bash -n "$ROOT/hooks/run-hook.cmd" && good "hooks/run-hook.cmd (валиден и как bash)" || bad "run-hook.cmd"

    CLAUDE_PLUGIN_ROOT="$ROOT" bash "$ROOT/hooks/session-start" \
        | python3 -c "import json,sys;d=json.load(sys.stdin);assert d['additional_context']" 2>/dev/null \
        && good "хук отдаёт валидный JSON" || bad "хук не отдал валидный JSON"

    # Ни одного домашнего пути в том, что ПОСТАВЛЯЕТСЯ — это и делает плагин
    # непереносимым. Проверяется отслеживаемое, а не всё на диске: артефакты
    # прогонов (evals/results, песочницы) несут абсолютные пути по своей
    # природе и в поставку не едут. docs/ освобождён — планы цитируют команды,
    # которые правда выполнялись на этой машине, и переписать их значило бы
    # соврать. Ищется ДОМ ТОГО, КТО СОБИРАЕТ ($HOME), а не любой путь вида
    # /Users/...: под второе попадает /Users/Shared/Adobe из комментария,
    # объясняющего ограду, и ворота начинают ругаться на документацию.
    hardpaths() {
        git -C "$ROOT" ls-files -z 2>/dev/null \
            | grep -zv '^docs/' | grep -zv '^dev\.sh$' \
            | xargs -0 grep -lIF "$HOME/" 2>/dev/null
    }
    if hardpaths | head -3 | grep -q .; then
        bad "домашние пути в поставляемом — плагин непереносим:"
        hardpaths | sed 's|.*|    &|'
    else
        good "жёстких путей нет"
    fi

    if claude plugin validate "$ROOT" 2>&1 | tail -3; then
        good "манифест валиден"
    else
        bad "claude plugin validate отверг плагин — он не установится"
        ok=1
    fi
    return $ok
}

cmd_publish() {
    cd "$ROOT" || return 1
    # НИКАКОГО git add -A. В дереве бывают чужие незаконченные правки — свои же
    # агенты, соседняя сессия, недоделанный эксперимент, — и `add -A` уносит их
    # в общий коммит и в push, откуда не вернёшь. Публикуется только то, что
    # УЖЕ застейджено осознанно.
    if ! git diff --cached --quiet; then
        :
    elif [ -n "$(git status --porcelain)" ]; then
        bad "в дереве есть неподготовленные изменения — застейджите то, что публикуете:"
        git status --short | sed 's|.*|    &|'
        say "  git add <файлы> && ./dev.sh publish \"сообщение\""
        return 1
    else
        say "нечего публиковать"; return 0
    fi
    local msg="${1:-cckit: правки}"
    git -c user.name="drshpackz" -c user.email="arinasnorge@gmail.com" commit -q -m "$msg

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>" || return 1
    git push -q origin main || { say "пуш не прошёл"; return 1; }
    say "опубликовано: $(git log --oneline -1)"
}

cmd_reinstall() {
    say "== переустановка =="
    local src="${1:-$ROOT}"     # local path by default; pass drshpackz/cckit-plugin for the published one
    claude plugin uninstall "$PLUGIN" 2>/dev/null | tail -1
    claude plugin marketplace remove "$MARKET" 2>/dev/null | tail -1
    claude plugin marketplace add "$src" 2>&1 | tail -2
    claude plugin install "${PLUGIN}@${MARKET}" 2>&1 | tail -2
    say "== установлено =="
    claude plugin list 2>&1 | grep -i cckit || say "  в списке нет — смотри вывод выше"
}

# `all` без eval: он тратит деньги и ходит в сеть, а `all` гоняют по десять раз
# на дню. CCKIT_LIVE=1 — та же ручка, которой в наборе включаются живые прогоны.
cmd_all() {
    cmd_check || return 1
    if [ "${CCKIT_LIVE:-0}" = "1" ]; then
        cmd_eval || return 1
    else
        say "== срабатывание скиллов ==  пропущено (CCKIT_LIVE=1 — прогнать; это деньги и сеть)"
    fi
    cmd_publish "${1:-cckit: правки}" && cmd_reinstall
}

case "${1:-check}" in
    check)     cmd_check ;;
    test)      cmd_test ;;
    eval)      shift; cmd_eval ${1:+"$@"} ;;
    publish)   cmd_publish "${2:-}" ;;
    reinstall) cmd_reinstall "${2:-}" ;;
    all)       cmd_all "${2:-cckit: правки}" ;;
    *) say "dev.sh check | test | eval [флаги] | publish [сообщение] | reinstall [источник] | all [сообщение]" ;;
esac
