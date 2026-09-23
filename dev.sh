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

cmd_check() {
    say "== проверка =="
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

    # The suite itself is part of the gate. Without this `check` passed on a
    # red suite, which is the same as having no suite at all.
    local out
    if out="$(cd "$ROOT" && python3 -m unittest discover -s tests 2>&1)"; then
        good "тесты — $(printf '%s' "$out" | grep -o 'Ran [0-9]* test[s]*')"
    else
        bad "тесты — набор красный:"
        printf '%s\n' "$out" | tail -20 | sed 's|.*|    &|'
    fi

    claude plugin validate "$ROOT" 2>&1 | tail -3
    return $ok
}

cmd_publish() {
    cd "$ROOT" || return 1
    git add -A
    if git diff --cached --quiet; then say "нечего публиковать"; return 0; fi
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

case "${1:-all}" in
    check)     cmd_check ;;
    publish)   cmd_publish "${2:-}" ;;
    reinstall) cmd_reinstall "${2:-}" ;;
    all)       cmd_check && cmd_publish "${2:-cckit: правки}" && cmd_reinstall ;;
    *) say "dev.sh check | publish [сообщение] | reinstall [источник] | all [сообщение]" ;;
esac
