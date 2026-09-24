#!/usr/bin/env python3
"""Библиотека компонентов: манифесты → каталог → заказ → сборка юнита → установка.

Источник правды — манифесты в git рядом с компонентами (`component.yaml`, у хуков —
`components/hooks/<id>.yaml`). Каталог (library.json, LIBRARY.md) генерируется, руками не
правится. Версия детали — по СОДЕРЖИМОМУ: sha256[:12] от манифеста и её файлов; поле `commit` —
последний коммит, только для справки. Поэтому каталог пересобирается в том же коммите, где
меняется деталь, и опубликованный library.json не отстаёт от файлов рядом с ним.
Заказ — не чтение таблицы: основной агент называет, ЧТО нужно ассистенту, решатель подбирает
компоненты по `provides`.

  cckit_library.py index            — library.json + LIBRARY.md из манифестов
  cckit_library.py needs            — что можно заказать и кто это даёт
  cckit_library.py find ЗАПРОС      — поиск по компонентам и ролям
  cckit_library.py order [--role ОСНОВА] --needs a,b [--ledger ПУТЬ] [--records ПАПКА] [--json]
  cckit_library.py build --role ОСНОВА --needs a,b --name ЮНИТ [--ledger ..] [--records ..] [--force]
                         [--install --project ПАПКА [--i-mean-it]]
  cckit_library.py fetch --needs a,b --to ПАПКА [--ref SHA | --from gh:ВЛАДЕЛЕЦ/РЕПО@REF]
"""
import ast
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDERABLE = ("works", "wired-later")
# То же правило имени, что у установщика: юнит, который он не примет, не собирается вовсе.
UNIT_NAME = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
RAW = "https://raw.githubusercontent.com/%s/%s/%s/%s"
GH = re.compile(r"^gh:(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)(?:@(?P<ref>[\w./-]+))?$")


def _git(*args):
    try:
        return subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True, check=True).stdout
    except Exception:
        return None


def library_dir():
    """Куда build кладёт юнит — туда, где установщик ищет роль первой. Функция, а не
    константа: HOME и CCKIT_LIBRARY читаются в момент вызова."""
    return os.environ.get("CCKIT_LIBRARY") or os.path.join(os.path.expanduser("~"), ".cckit", "library")


def _listed():
    """Файлы репозитория, которые войдут в поставку: отслеживаемые и новые, без игнорируемых."""
    out = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if out is None:
        files = [os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, "/")
                 for d, _, fs in os.walk(ROOT) for f in fs]
        files = [f for f in files if not f.startswith(".git/")]
    else:
        files = [f for f in out.split("\0") if f]
    return sorted({f for f in files if "__pycache__" not in f and not f.endswith(".pyc")
                   and os.path.isfile(os.path.join(ROOT, f))})


def manifest_paths(listed=None):
    return [f for f in (listed if listed is not None else _listed())
            if f.endswith("component.yaml") or (f.startswith("components/") and f.endswith(".yaml"))]


def _expand(paths, listed):
    """`files:` манифеста называет и файлы, и папки; каталогу нужен точный список."""
    return sorted({f for p in paths for f in listed if f == p or f.startswith(p.rstrip("/") + "/")})


def _blob(rel):
    with open(os.path.join(ROOT, rel), "rb") as fh:
        return fh.read()


def digest(pairs):
    """[(путь, байты)] → версия. Путь входит в хэш: переименование — тоже новая версия.
    Концы строк приводятся к \\n: чекаут с autocrlf не должен менять версию."""
    h = hashlib.sha256()
    for path, data in sorted(pairs):
        h.update(path.encode("utf-8") + b"\0" + data.replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()[:12]


def _commit(paths):
    return (_git("log", "-1", "--format=%h", "--", *paths) or "").strip() or None


def parse(text):
    """Плоский YAML: `ключ: значение`, списки `[a, b]`, строки карточки через ` | `."""
    m = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = re.sub(r"\s+#.*$", "", v).strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
        m[k.strip()] = v
    for k in ("provides", "requires", "requires_input", "grants", "files", "writes", "hooks"):
        m[k] = m.get(k) or []
    if isinstance(m.get("card_lines"), str):
        m["card_lines"] = [x.strip() for x in m["card_lines"].split(" | ") if x.strip()]
    return m


def load():
    listed = _listed()
    comps = []
    for rel in manifest_paths(listed):
        c = parse(_blob(rel).decode("utf-8"))
        c["manifest"] = rel
        c["blobs"] = _expand(c["files"], listed)
        c["version"] = digest([(p, _blob(p)) for p in set([rel] + c["blobs"])])
        c["commit"] = _commit([os.path.dirname(rel)] if rel.endswith("component.yaml") else [rel] + c["files"])
        comps.append(c)
    return sorted(comps, key=lambda c: (c.get("kind", ""), c.get("id", "")))


def _installer_consts():
    """CAPS, BASE_CAPS, NEVER, DANGEROUS из установщика — разбором текста, без импорта:
    описание прав в каталоге обязано совпадать с тем, что установщик действительно выдаст."""
    tree = ast.parse(_blob(os.path.join("bin", "cckit_assistant.py")).decode("utf-8"))
    got = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", "") in ("CAPS", "BASE_CAPS", "NEVER", "DANGEROUS"):
            got[node.targets[0].id] = ast.literal_eval(node.value)
    return got


def roles():
    k = _installer_consts()
    listed = _listed()
    every = sorted({t for tools in k["CAPS"].values() for t in tools} | set(k["NEVER"]))
    out = []
    for d in sorted(os.listdir(os.path.join(ROOT, "assistants"))):
        cp = os.path.join(ROOT, "assistants", d, "card.yaml")
        if not os.path.isfile(cp):
            continue
        with open(cp, encoding="utf-8") as fh:
            c = parse(fh.read())
        caps = list(k["BASE_CAPS"]) + (["write"] if c.get("access") == "write-scoped" else [])
        allowed = sorted({t for cap in caps for t in k["CAPS"].get(cap, [])})
        blobs = _expand(["assistants/" + d], listed)
        out.append({"id": d, "kind": "role", "summary": c.get("summary", ""), "access": c.get("access", "read-only"),
                    "reads": "весь проект и свой дом", "writes": c["writes"] or ["— только свой дом (LEARNED.md, memory)"],
                    "tools_allowed": allowed, "tools_denied": [t for t in every if t not in allowed],
                    "grants_on_request": list(k["DANGEROUS"]) + [x for x in ("spawn", "web", "worktree", "design") if x in k["CAPS"]],
                    "hooks": c["hooks"], "model": c.get("model"), "effort": c.get("effort"), "compact_at": c.get("compact_at"),
                    "blobs": blobs, "version": digest([(p, _blob(p)) for p in blobs]),
                    "commit": _commit(["assistants/" + d])})
    return out


API = "https://raw.githubusercontent.com/drshpackz/cckit-plugin/main/library.json"


def index(out_dir=None):
    out_dir = out_dir or ROOT
    comps = load()
    rls = roles()
    with open(os.path.join(out_dir, "library.json"), "w", encoding="utf-8") as fh:
        json.dump({"components": comps, "roles": rls}, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    rows = ["| %s | %s | %s | %s | %s | %s |" % (c.get("id"), c.get("kind"), ", ".join(c["provides"]) or "—",
            c.get("status"), c.get("version"), c.get("summary", "")) for c in comps]
    rrows = ["| %s | %s | %s | %s | %s | %s | %s |" % (r["id"], r["summary"], ", ".join(r["writes"]), ", ".join(r["tools_allowed"]),
             ", ".join(r["tools_denied"]), ", ".join(r["hooks"]) or "—", r["model"]) for r in rls]
    with open(os.path.join(out_dir, "LIBRARY.md"), "w", encoding="utf-8") as fh:
        fh.write("# Библиотека компонентов\n\n"
                 "**Генерируется** из манифестов (`python3 bin/cckit_library.py index`) — руками не править.\n"
                 "Приём живёт тремя опорами: файл компонента, строка в карточке роли, проверка (`proof`\n"
                 "в манифесте). Заказ: `python3 bin/cckit_library.py order --needs …`.\n\n"
                 "Версия — sha256[:12] от манифеста и файлов детали, а не коммит: каталог собирается в\n"
                 "том же коммите, что и деталь. Машинный вид этой таблицы — API: " + API + "\n\n"
                 "| id | вид | даёт | статус | версия | что это |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
                 "\n## Роли — что каждая может, до установки\n\n"
                 "Права вычислены константами установщика: описание не может разойтись с тем, что роль получит.\n"
                 "Читают все роли весь проект и свой дом. Опасные группы — только по явной выдаче при установке.\n\n"
                 "| роль | для чего | пишет | разрешено | запрещено | хуки | модель |\n|---|---|---|---|---|---|---|\n"
                 + "\n".join(rrows) + "\n")
    return comps + rls


def needs():
    by = {}
    for c in load():
        if c.get("status") in ORDERABLE:
            for n in c["provides"]:
                by.setdefault(n, []).append("%s (%s)" % (c["id"], c.get("status")))
    return by


def order(wanted, inputs, comps=None):
    """Заказ по нуждам. `comps` — чужой каталог (скачанный library.json); иначе — свой."""
    comps = [c for c in (load() if comps is None else comps) if c.get("status") in ORDERABLE and c.get("kind") != "skill"]
    chosen, missing, errors = [], [], []
    for n in wanted:
        hit = [c for c in comps if n in c["provides"]]
        if not hit:
            missing.append(n)
        for c in hit:
            if c not in chosen:
                chosen.append(c)
    card, lines, role, grants, later = {}, [], [], [], []
    for c in chosen:
        for need in c["requires_input"]:
            if not inputs.get(need):
                errors.append("%s требует --%s" % (c["id"], need))
        if c.get("card_key"):
            card.setdefault(c["card_key"], []).append(c["card_value"])
            if c.get("status") == "wired-later":
                later.append(c["card_key"])
        lines += c.get("card_lines") or []
        if c.get("role_text"):
            role.append(c["role_text"])
        grants += [g for g in c["grants"] if g not in grants]
    # Каждый ввод (ledger, records, …) — строка карточки: его читает деталь, которой он нужен.
    lines += ["%s: %s" % (k, v) for k, v in inputs.items() if v]
    return {"components": [c["id"] for c in chosen], "card": card, "card_lines": lines,
            "role_text": role, "grants": grants, "wired_later": later,
            "not_found": missing, "errors": errors}


CARD_ORDER = ("name", "summary", "access", "writes", "model", "effort", "budget_usd", "compact_at", "hooks",
              "ledger", "records", "formats")


def assemble(role, wanted, inputs, name=None):
    """Юнит = роль-основа + детали. Итоговая card.yaml, добавки в ROLE.md, выдача, файлы."""
    cp = os.path.join(ROOT, "assistants", role, "card.yaml")
    if not os.path.isfile(cp):
        return {"errors": ["нет роли-основы «%s»; есть: %s" % (role, ", ".join(r["id"] for r in roles()))]}
    with open(cp, encoding="utf-8") as fh:
        base = parse(fh.read())
    o = order(wanted, inputs)
    card = {k: v for k, v in base.items() if v not in ([], None, "")}
    if name:
        card["name"] = name
    for key, vals in o["card"].items():
        card[key] = list(dict.fromkeys(list(card.get(key) or []) + vals))
    for line in o["card_lines"]:
        k, _, v = line.partition(":")
        card[k.strip()] = v.strip()
    text = []
    for k in list(CARD_ORDER) + [k for k in card if k not in CARD_ORDER]:
        if k in card:
            v = card[k]
            text.append("%s: %s" % (k, "[%s]" % ", ".join(('"%s"' % x) if k == "writes" else x for x in v) if isinstance(v, list) else v))
    o.update({"role": role, "card_yaml": "\n".join(text) + "\n", "fetch": sorted({f for c in load() if c["id"] in set(o["components"]) | set(card.get("hooks") or []) | set(card.get("formats") or []) for f in c["files"]})})
    return o


def unit_role_md(base_md, u):
    """ROLE.md юнита: основа + раздел «Детали юнита» со строками деталей. Сами файлы
    формата (шаблон, линтер) доставляет в дом установщик по ключу `formats:` карточки."""
    if not u["role_text"]:
        return base_md
    return base_md.rstrip("\n") + "\n\n# Детали юнита\n\n" + "".join("- %s\n" % t for t in u["role_text"])


def installer_argv(name, project, grants, force=False, i_mean_it=False):
    argv = [sys.executable, os.path.join(ROOT, "bin", "cckit_assistant.py"), "install", name, "--project", project]
    if grants:
        argv += ["--grant", ",".join(grants)]
    if force:
        argv.append("--force")
    if i_mean_it:
        argv.append("--i-mean-it")
    return argv


def build(role, wanted, name, inputs, force=False, project=None, i_mean_it=False, run=None, say=print):
    """Сборочный лист → роль-юнит в библиотеке пользователя → (с project) установка.

    Возвращает код. Существующую роль в библиотеке не трогает без force: там может лежать
    чужая работа. --i-mean-it доходит до установщика, только если его передал человек."""
    if not UNIT_NAME.match(name or ""):
        say("ОШИБКА: имя юнита «%s»: строчная латиница, цифры, дефис, 2–40 знаков" % name)
        return 2
    u = assemble(role, wanted, inputs, name=name)
    if "components" not in u:
        say("ОШИБКА: " + u["errors"][0])
        return 1
    bad = u["errors"] + ["не нашлось детали для «%s» — см. `needs`" % n for n in u["not_found"]]
    if bad:
        for e in bad:
            say("ОШИБКА: " + e)
        return 1
    role_md = os.path.join(ROOT, "assistants", role, "ROLE.md")
    if not os.path.isfile(role_md):
        say("ОШИБКА: у роли-основы «%s» нет ROLE.md" % role)
        return 1
    dst = os.path.join(library_dir(), name)
    if os.path.exists(os.path.join(dst, "card.yaml")) and not force:
        say("ОШИБКА: роль «%s» уже есть в библиотеке: %s — перезаписать: --force" % (name, dst))
        return 1
    with open(role_md, encoding="utf-8") as fh:
        body = unit_role_md(fh.read(), u)
    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(dst, "card.yaml"), "w", encoding="utf-8") as fh:
        fh.write(u["card_yaml"])
    with open(os.path.join(dst, "ROLE.md"), "w", encoding="utf-8") as fh:
        fh.write(body)
    say("юнит «%s» = роль «%s» + %s → %s" % (name, role, ", ".join(u["components"]) or "—", dst))
    for k in u["wired_later"]:
        say("  %s: деталь в карточке, установщик её пока не доставляет — работает строкой в ROLE.md" % k)
    argv = installer_argv(name, project or "ПАПКА", u["grants"], force, i_mean_it)
    if not project:
        say("поставить: python3 " + " ".join(argv[1:]).replace(ROOT + os.sep, ""))
        return 0
    return (run or subprocess.call)(argv)


def find(query):
    q = query.lower()
    return [x for x in load() + roles() if q in (" ".join([x.get("id", ""), x.get("summary", "")] + list(x.get("provides", [])))).lower()]


def fetch(wanted, to, ref="HEAD", inputs=None):
    """Скачать заказанные компоненты из git в версии ref — только их, не всю библиотеку."""
    ids = order(wanted, inputs or {})["components"]
    got = []
    for c in load():
        if c["id"] not in ids:
            continue
        for path in c["files"]:
            listed = (_git("ls-tree", "-r", "--name-only", ref, "--", path) or "").split()
            for f in listed:
                blob = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (ref, f)], capture_output=True, check=True).stdout
                dst = os.path.join(to, f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as fh:
                    fh.write(blob)
                got.append(f)
    return sorted(set(got))


def _http_get(url):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()
    except OSError as e:   # URLError и HTTPError — подклассы OSError
        raise ValueError("не скачалось %s: %s" % (url, e))


def _safe(path):
    if not path or path.startswith(("/", "\\")) or "\\" in path or ":" in path or ".." in path.split("/"):
        raise ValueError("отказ: в каталоге путь вне репозитория: %r" % path)
    return path


def fetch_gh(spec, wanted, to, inputs=None, get=None):
    """Скачать заказанное из опубликованного каталога: gh:ВЛАДЕЛЕЦ/РЕПО@REF.

    Каждая деталь сверяется с version-хэшем каталога; одна не сошлась — не пишется ничего."""
    m = GH.match(spec or "")
    if not m:
        raise ValueError("--from ждёт gh:ВЛАДЕЛЕЦ/РЕПО[@REF], а не %r" % spec)
    import urllib.parse
    get = get or _http_get

    def url(p):
        return RAW % (m.group("owner"), m.group("repo"), m.group("ref") or "main", urllib.parse.quote(p))

    cat = json.loads(get(url("library.json")).decode("utf-8"))
    ids = order(wanted, inputs or {}, comps=cat["components"])["components"]
    got, bad = {}, []
    for c in cat["components"]:
        if c["id"] not in ids:
            continue
        if "blobs" not in c:
            bad.append("%s: каталог старого образца, без списка файлов — версию нечем сверить" % c["id"])
            continue
        pairs = [(p, get(url(_safe(p)))) for p in sorted(set([c["manifest"]] + c["blobs"]))]
        have = digest(pairs)
        if have != c["version"]:
            bad.append("%s: в каталоге %s, по содержимому %s" % (c["id"], c["version"], have))
            continue
        got.update({p: d for p, d in pairs if p in c["blobs"]})
    if bad:
        raise ValueError("отказ: содержимое не сходится с каталогом —\n  " + "\n  ".join(bad))
    for p, data in got.items():
        dst = os.path.join(to, *p.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
    return sorted(got)


def _flags(argv, switches=()):
    """--ключ значение → {ключ: значение}; --переключатель → {переключатель: True}."""
    got, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a in switches:
            got[a[2:]] = True; i += 1
        elif a.startswith("--") and i + 1 < len(argv):
            got[a[2:]] = argv[i + 1]; i += 2
        else:
            raise ValueError("неизвестный флаг: " + a)
    return got


def _needs(f):
    return [x.strip() for x in (f.pop("needs", "") or "").split(",") if x.strip()]


def main(argv):
    if argv and argv[0] == "find" and len(argv) > 1:
        for x in find(" ".join(argv[1:])):
            print("%-16s %-9s %s" % (x["id"], x.get("kind"), x.get("summary", "")))
        return 0
    if not argv or argv[0] not in ("index", "needs", "order", "build", "fetch"):
        print(__doc__.strip()); return 2
    if argv[0] == "index":
        print("компонентов: %d → library.json, LIBRARY.md" % len(index())); return 0
    if argv[0] == "needs":
        for n, who in sorted(needs().items()):
            print("%-18s %s" % (n, ", ".join(who)))
        return 0
    try:
        f = _flags(argv[1:], ("--json", "--install", "--force", "--i-mean-it"))
    except ValueError as e:
        print(e); return 2
    want = _needs(f)
    if argv[0] == "fetch":
        to, ref, src = f.pop("to", None), f.pop("ref", "HEAD"), f.pop("from", None)
        if not want or not to:
            print("fetch --needs a,b --to ПАПКА [--ref SHA | --from gh:ВЛАДЕЛЕЦ/РЕПО@REF]"); return 2
        try:
            got = fetch_gh(src, want, to, f) if src else fetch(want, to, ref, f)
        except ValueError as e:
            print(e); return 1
        for p in got:
            print("  " + p)
        return 0
    if argv[0] == "build":
        role, name, project = f.pop("role", None), f.pop("name", None), f.pop("project", None)
        install, force, i_mean_it = f.pop("install", False), f.pop("force", False), f.pop("i-mean-it", False)
        f.pop("json", None)
        if not role or not name or not want:
            print("build --role ОСНОВА --needs a,b --name ЮНИТ [--ledger ..] [--records ..] [--force] "
                  "[--install --project ПАПКА [--i-mean-it]]"); return 2
        if install and not project:
            print("--install ставит в проект: нужен --project ПАПКА"); return 2
        return build(role, want, name, f, force=force, project=project if install else None, i_mean_it=i_mean_it)
    as_json = f.pop("json", False)
    for k in ("install", "force", "i-mean-it"):
        if f.pop(k, False):
            print("неизвестный флаг: --" + k); return 2
    role = f.pop("role", None)
    inputs = f
    r = assemble(role, want, inputs) if role else order(want, inputs)
    if r.get("errors") and "components" not in r:
        print("ОШИБКА: " + r["errors"][0]); return 1
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(("юнит на основе роли «%s»; детали: " % role if role else "компоненты: ") + (", ".join(r["components"]) or "—"))
        if role:
            print("\ncard.yaml целиком:\n" + "".join("  " + l + "\n" for l in r["card_yaml"].splitlines()))
            print("скачать из git: " + (", ".join(r["fetch"]) or "—"))
        print("\nв card.yaml:")
        for k, v in r["card"].items():
            print("  %s: [%s]%s" % (k, ", ".join(v), "   # установщик пока не доставляет — см. ROLE.md" if k in r["wired_later"] else ""))
        for l in r["card_lines"]:
            print("  " + l)
        if r["role_text"]:
            print("\nв ROLE.md:"); [print("  - " + t) for t in r["role_text"]]
        if r["grants"]:
            print("\nпри установке: --grant " + ",".join(r["grants"]))
        if role and not r["errors"]:
            print("\nсобрать и поставить: python3 bin/cckit_library.py build --role %s --needs %s --name ЮНИТ --install --project ПАПКА"
                  % (role, ",".join(want)))
        for n in r["not_found"]:
            print("\nне нашлось компонента для «%s» — см. `needs`" % n)
        for e in r["errors"]:
            print("\nОШИБКА: " + e)
    return 1 if r["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
