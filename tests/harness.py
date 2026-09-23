"""A temporary home, a fake `claude` on PATH, and the guarantee that neither
outlives the test.

The sandbox deletes trees, so the question it has to answer honestly is not
"where is this directory" but "who made it". Geography is derived from the
environment — TMPDIR set before this process started moves the anchor wherever
an attacker likes — and no amount of freezing changes that the answer still
came from outside. Provenance is not: a directory the sandbox created itself
was empty when it took it, and carries a marker file it wrote there. That
marker, not the path, is what licenses `shutil.rmtree`.
"""

import json
import os
import shutil
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# TMPDIR/TMP/TEMP are in here because the anchor check still reads the
# temporary directory: a test that moves them and forgets to move them back
# would hand the next sandbox a different anchor. The anchor is no longer what
# makes deletion safe, but it is still a check that must mean the same thing
# from one test to the next.
VARS = ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "PATH", "CCKIT_FAKE_STATE",
        "CCKIT_LIBRARY", "TMPDIR", "TMP", "TEMP")

# The file the sandbox drops in its own root on the way in. Its presence is the
# entire right to delete that tree on the way out.
MARKER = ".cckit-sandbox"


def _pwd_home():
    """The account's home as the password database states it — the one answer
    no environment variable can change. `os.path.expanduser` reads HOME first,
    so it is worth exactly as much as whoever set HOME last."""
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        # No pwd module (Windows). Frozen at import is still better than live.
        return os.path.expanduser("~")


# Taken HERE, at import, before any test body has run. Freezing does not make
# the anchor trustworthy — it was read from an environment that may have been
# hostile before this module was imported — it only makes it STABLE, so the
# same root gets the same answer for the whole run.
_ANCHOR = os.path.realpath(tempfile.gettempdir())
_PWD_HOME = os.path.realpath(_pwd_home())


def _real(p):
    # normcase folds case on Windows and does nothing at all on macOS, where
    # realpath does not fold case either. So this string is NOT what makes the
    # comparisons below case-proof — `_same_path` asks the filesystem, which
    # knows. normcase stays for Windows path separators and drive letters.
    return os.path.normcase(os.path.realpath(p))


def _same_path(a, b):
    """Same directory? The filesystem is asked first: on a case-insensitive
    volume `/tmp/Me` and `/tmp/me` are one directory and only `os.stat` says
    so. Strings are the fallback for paths that do not exist yet."""
    try:
        if os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return _real(a) == _real(b)


def _under(child, parent):
    """True when `child` lies strictly inside `parent`; walks up the parents so
    every step gets the same filesystem-aware comparison."""
    cur = _real(child)
    while True:
        nxt = os.path.dirname(cur)
        if nxt == cur:
            return False
        cur = nxt
        if _same_path(cur, parent):
            return True


def _home_candidates():
    """Every path that might be somebody's home right now. The first entry is
    the environment-proof one; the rest only ever make the guard stricter."""
    out = []
    for h in (_PWD_HOME, os.environ.get("HOME"), os.environ.get("USERPROFILE"),
              os.path.expanduser("~")):
        if h and h not in out:
            out.append(h)
    return out


def _expand_tilde(p):
    """`~` is expanded HERE or refused HERE — never carried further as a
    literal directory name. Left alone, '~/.cckit/assistants/x' is just a
    relative path: `abspath` glues it to the cwd and the guard then answers a
    question about a directory nobody meant, so the one verdict it must give —
    "that is the home" — is the one verdict it never gives.

    `os.path.expanduser` is not used: it reads HOME first, and HOME is exactly
    what the sandbox spends its life moving. The password database answers."""
    if not p.startswith("~"):
        return p
    rest = p[1:]
    if rest[:1] in ("", "/", os.sep):
        return _PWD_HOME + rest
    # ~someone/... — resolvable only through the password database.
    name = rest.replace(os.sep, "/").split("/")[0]
    try:
        import pwd
        base = pwd.getpwnam(name).pw_dir
    except Exception:
        raise AssertionError(
            "корень песочницы отвергнут: %s — тильда указывает на пользователя "
            "%r, которого нет в базе паролей, и раскрыть её некуда" % (p, name))
    return base + rest[len(name):]


def check_root(root):
    """The rule that REFUSES — asked in the constructor, on the way in, and
    again inside `__exit__` right before `rmtree`, where it is the last thing
    between the argument and the tree.

    It does not grant anything. The right to delete comes from the marker file
    `Sandbox` writes into a root that was empty when it took it (see
    `_require_virgin` and `_read_marker`): the sandbox deletes only what the
    sandbox made. Everything here only refuses sooner, with a readable reason.

    THREE conditions, all required:

    1. The root is an absolute path with `~` already expanded, so every later
       answer is about the same tree no matter whose cwd or HOME is current.
    2. It may not BE a home, may not CONTAIN one, and may not lie INSIDE one.
       This asks the password database, not the environment, so it holds even
       for a caller who has made the whole home look temporary — it is what
       refuses `~/.cckit/assistants/…`.
    3. It must lie strictly inside the temporary directory as it was at import.

    Condition 3 is NOT a defence against a hostile pre-import environment, and
    it was wrong to claim so: `TMPDIR=/Users/Shared` exported before Python
    starts makes `/Users/Shared` the anchor, and `pwd` — which knows only about
    the home — has nothing to say about `/Users/Shared/Adobe`. What stops that
    root is provenance: `/Users/Shared/Adobe` is not empty, so `__enter__`
    refuses it, and it carries no marker, so `__exit__` would refuse to delete
    it even if it somehow got that far. Condition 3 survives because a stable
    white list still catches ordinary mistakes early and names them clearly.

    Returns the root resolved with `realpath` — the very path that was judged,
    not a cousin of it. `abspath` leaves symlinks in place, so the string that
    came back used to be one the checks had never looked at.
    """
    if not isinstance(root, str) or not root.strip():
        raise AssertionError(
            "корень песочницы отвергнут: пустой путь (%r) — это не каталог, а "
            "приглашение удалить текущий рабочий каталог" % (root,))

    root = os.path.abspath(_expand_tilde(root))

    # A symlink root is refused by name: `realpath` below would answer about
    # the target while `rmtree` and the residue check answer about the link.
    if os.path.islink(root):
        raise AssertionError(
            "корень песочницы отвергнут: %s — это символическая ссылка, и "
            "проверять пришлось бы одно дерево, а удалять другое" % root)

    root = os.path.realpath(root)

    for home in _home_candidates():
        if _same_path(root, home):
            raise AssertionError(
                "корень песочницы отвергнут: %s — это настоящий дом %s"
                % (root, home))
        if _under(home, root):
            raise AssertionError(
                "корень песочницы отвергнут: %s — внутри него лежит настоящий "
                "дом %s, который выход стёр бы вместе с деревом" % (root, home))
        if _under(root, home):
            raise AssertionError(
                "корень песочницы отвергнут: %s — он лежит внутри настоящего "
                "дома %s, где живут рабочие ассистенты" % (root, home))

    if not _under(root, _ANCHOR):
        raise AssertionError(
            "корень песочницы отвергнут: %s — он не лежит внутри временного "
            "каталога %s, а удалять при выходе можно только там"
            % (root, _ANCHOR))
    return root


def _require_virgin(root):
    """The root must be EMPTY or absent at the moment of entry.

    This is the whole of the new rule, and it is not about paths. A directory
    with anything in it is somebody's data — `/Users/Shared/Adobe` under a
    doctored TMPDIR, `~/.cckit` under a doctored HOME, a project checkout
    someone passed by mistake. The sandbox never adopts a populated directory,
    so it never has to argue about whether it was allowed to delete one.
    """
    if not os.path.lexists(root):
        return
    if not os.path.isdir(root):
        raise AssertionError(
            "корень песочницы отвергнут: %s существует и это не каталог" % root)
    entries = sorted(os.listdir(root))
    if entries:
        raise AssertionError(
            "корень песочницы отвергнут: %s не пуст (%s) — непустой каталог "
            "это чужие данные, что бы ни говорил о нём путь; песочница берёт "
            "только пустой или несуществующий корень"
            % (root, ", ".join(entries[:5])))


def _read_marker(root):
    """The marker this process wrote, or None. Never raises: an unreadable,
    malformed or foreign marker is simply not a licence."""
    p = os.path.join(root, MARKER)
    if os.path.islink(p) or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


class Sandbox(object):
    def __init__(self, root=None):
        """`root` exists only so the guard can be exercised by a test. Left at
        None — which is every real use — the root is a fresh temporary
        directory that cannot be anybody's home.

        The refusals run here, in the constructor: a refused root is refused
        before a single directory exists, so there is nothing to clean up and
        nothing for a broken guard to delete.
        """
        # Set before anything can fail: `__exit__` uses it to tell "entered"
        # from "never entered", and must stay a no-op in the second case.
        self._saved = None
        self._entered = False
        self._token = None
        self._checked_root = None
        self.root = None
        if root is not None:
            root = check_root(root)
        self._given_root = root

    # ── Derived directories ────────────────────────────────────────────────
    # Not attributes. `self.state` and `self.bin` used to be plain strings set
    # once at entry, which meant `sb.state = "/чужое"` was enough to make
    # `set_reply` write into someone else's directory and `_install_fake` drop
    # an executable there — two writes outside the sandbox that no guard on the
    # ROOT could ever see. Read-only properties derived, at the moment of use,
    # from the root that actually passed `check_root` on the way in.
    #
    # `check_root` is not re-run here on purpose: while the sandbox is entered,
    # HOME points INSIDE the root, so the home rules would (correctly, by their
    # own logic) refuse the sandbox's own root. The question these need to ask
    # is narrower — "is this still the root that was verified?" — and a swapped
    # `self.root` is exactly what it catches.

    def _sub(self, name):
        root = self._checked_root
        if root is None:
            raise AssertionError(
                "песочница не вошла: каталоги считать не от чего")
        if self.root != root:
            raise AssertionError(
                "корень песочницы подменён после входа (%s вместо проверенного "
                "%s) — производные каталоги считать не от чего"
                % (self.root, root))
        return os.path.join(root, name)

    @property
    def home(self):
        return self._sub("home")

    @property
    def project(self):
        return self._sub("project")

    @property
    def bin(self):
        return self._sub("bin")

    @property
    def state(self):
        return self._sub("state")

    # ── Entry ──────────────────────────────────────────────────────────────

    def __enter__(self):
        # A second entry on the same object overwrites `_saved` with a snapshot
        # of the ALREADY doctored environment, and the single `__exit__` then
        # "restores" that forgery: HOME left pointing at a deleted sandbox and
        # the fake `claude` left first on PATH for the rest of the process.
        # There is no correct way to nest, so there is no nesting.
        if self._entered:
            raise AssertionError(
                "повторный вход в ту же песочницу запрещён: второй __enter__ "
                "запомнил бы уже подменённое окружение, и выход восстановил бы "
                "подделку — настоящее окружение было бы потеряно навсегда")
        self._entered = True

        made = self._given_root is None
        raw = self._given_root or os.path.abspath(
            tempfile.mkdtemp(prefix="cckit-test-"))
        try:
            # Checked again because the root may have come from mkdtemp — which
            # reads the live `tempfile.tempdir`, not our anchor.
            root = check_root(raw)
            _require_virgin(root)
        except AssertionError:
            if made:
                # os.rmdir, not rmtree: mkdtemp leaves it empty, and a refused
                # root is the last place to start deleting recursively.
                try:
                    os.rmdir(raw)
                except OSError:
                    pass
            raise

        self.root = root
        self._checked_root = root
        self._saved = {k: os.environ.get(k) for k in VARS}
        # Everything from here on is undone by the `except` below. `with` does
        # NOT call `__exit__` when `__enter__` raises, so an exception thrown
        # after the first `os.environ[...] = ...` — `_install_fake` does
        # `open` and `chmod`, either of which can fail on permissions or a full
        # disk — used to leak the doctored environment into the whole process.
        try:
            os.makedirs(root, exist_ok=True)
            self._write_marker(root)
            for d in (self.home, self.project, self.bin, self.state):
                os.makedirs(d)

            os.environ["HOME"] = self.home
            os.environ["USERPROFILE"] = self.home
            os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.home, ".claude")
            os.environ["CCKIT_FAKE_STATE"] = self.state
            # Saved in VARS and dropped here: inherited from the owner's shell
            # it would point the installer's role library back out of the
            # sandbox. Gone, it falls back to ~/.cckit/library — inside this
            # home.
            os.environ.pop("CCKIT_LIBRARY", None)
            os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
            self._install_fake()
        except BaseException:
            self._restore_env()
            # Marker-gated like every other delete: if the failure happened
            # before the marker was written, nothing is removed.
            self._destroy(quiet=True)
            self.root = None
            self._checked_root = None
            raise
        return self

    def _write_marker(self, root):
        self._token = "%d-%d-%d" % (os.getpid(), int(time.time() * 1000),
                                    int.from_bytes(os.urandom(4), "big"))
        payload = {"pid": os.getpid(), "token": self._token,
                   "created": time.time(), "root": root,
                   "argv0": os.path.basename(sys.argv[0] or "")}
        with open(os.path.join(root, MARKER), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)

    def _install_fake(self):
        fake = os.path.join(HERE, "fake_claude.py")
        binned = self.bin
        sh = os.path.join(binned, "claude")
        with open(sh, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, fake))
        os.chmod(sh, os.stat(sh).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # On Windows the real `claude` is an npm shim named claude.cmd, so the
        # fake wears the same name. Nothing in subprocess finds it: CreateProcess
        # appends only '.exe' and never reads PATHEXT — `run_claude` resolves
        # the name through shutil.which, which does, and that is what makes this
        # file reachable there.
        with open(os.path.join(binned, "claude.cmd"), "w", encoding="utf-8") as fh:
            fh.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, fake))

    def set_reply(self, result, session_id="s1", transcript_prompt=None, cost=0.0):
        d = {"result": result, "session_id": session_id, "total_cost_usd": cost}
        if transcript_prompt is not None:
            d["transcript_prompt"] = transcript_prompt
        with open(os.path.join(self.state, "reply.json"), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)

    def calls(self):
        p = os.path.join(self.state, "calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    # ── Exit ───────────────────────────────────────────────────────────────

    def _restore_env(self):
        if self._saved is None:
            return
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._saved = None

    @staticmethod
    def _assert_gone(root):
        # `lexists`, not `exists`: `exists` follows the link and answers about
        # the target, so a root that survived `rmtree` as a dangling symlink
        # reports False and the leak passes in silence. `lexists` asks about
        # the entry itself.
        if os.path.lexists(root):
            raise AssertionError(
                "песочница не убрана: %s пережил rmtree — дерево осталось на "
                "диске, и следующий прогон начнётся не с чистого места" % root)

    def _destroy(self, quiet=False):
        """Delete the root — but only on the marker's say-so.

        `check_root` has already refused the obvious disasters; this is the
        positive permission. A directory with no marker of ours in it was not
        made by this sandbox, and nothing about its path can change that.
        """
        if self.root is None:
            return
        root = check_root(self.root)
        mark = _read_marker(root)
        if mark is None or mark.get("token") != self._token:
            if quiet:
                return
            raise AssertionError(
                "уборка отменена: в %s нет метки %s этой песочницы — значит "
                "каталог создан не ею, и удалять его она не вправе"
                % (root, MARKER))
        shutil.rmtree(root, ignore_errors=True)
        # ignore_errors swallows every failure: a permission error, a busy
        # file. Silence there means directories pile up under a green suite,
        # so the result is checked, not assumed.
        self._assert_gone(root)

    def __exit__(self, *exc):
        # Never entered — or entered and refused. Nothing was saved, so there
        # is nothing to restore and, above all, nothing to delete.
        if self._saved is None:
            return False
        # The environment goes back first: whatever the guard decides about the
        # tree, the process must not be left with a doctored HOME and PATH.
        self._restore_env()
        # `self.root` is an ordinary attribute anyone can reassign between
        # entry and here, so both questions are asked again from scratch: the
        # refusals in `check_root`, and then the marker, which is the only
        # thing that actually grants the rmtree.
        self._destroy()
        return False
