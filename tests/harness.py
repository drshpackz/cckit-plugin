"""A temporary home, a fake `claude` on PATH, and the guarantee that neither
outlives the test."""

import json
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# TMPDIR/TMP/TEMP are in here because the sandbox's own white list is anchored
# on the temporary directory: a test that moves them and forgets to move them
# back would hand the next sandbox a different anchor.
VARS = ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "PATH", "CCKIT_FAKE_STATE",
        "CCKIT_LIBRARY", "TMPDIR", "TMP", "TEMP")


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


# Both snapshots are taken HERE, at import, before any test body has run and so
# before any test could move TMPDIR or assign `tempfile.tempdir`. Reading them
# live — which is what `tempfile.gettempdir()` does — puts the white list under
# the control of the very code it is meant to fence in.
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


def check_root(root):
    """The one rule that decides what may be deleted — asked in the constructor,
    asked on the way in, and asked again inside the `rmtree` call itself, where
    it is the only thing standing between the argument and the tree.

    TWO conditions, both required:

    1. A white list: the root MUST lie inside the temporary directory as it was
       at import time. Listing dangerous roots instead ends one case short of
       safe every time; under this rule '/' and the home simply fail to be
       temporary. Strictly inside, so the temporary directory itself is not
       deletable either.
    2. The anchor above still came from an environment that could have been
       hostile before this module was imported, so it cannot be trusted alone.
       The second condition asks the password database instead of the
       environment: the root may not BE a home, may not CONTAIN one, and may
       not lie INSIDE one. This one is checked whatever the anchor turns out
       to be — it is what refuses `~/.cckit/assistants/…` even to a caller who
       has made the whole home look temporary.

    Returns the root made absolute, or raises before anything has been created.
    """
    if not isinstance(root, str) or not root.strip():
        raise AssertionError(
            "корень песочницы отвергнут: пустой путь (%r) — это не каталог, а "
            "приглашение удалить текущий рабочий каталог" % (root,))

    # Absolute once, here, so that every later answer is about the same tree.
    # A relative root is resolved against the cwd of whoever asks, and the cwd
    # between the check and the rmtree is not the same cwd.
    root = os.path.abspath(root)

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


class Sandbox(object):
    def __init__(self, root=None):
        """`root` exists only so the guard can be exercised by a test. Left at
        None — which is every real use — the root is a fresh temporary
        directory that cannot be anybody's home.

        The guard runs here, in the constructor: a refused root is refused
        before a single directory exists, so there is nothing to clean up and
        nothing for a broken guard to delete. It runs twice more after this.
        """
        # Set before anything can fail: `__exit__` uses it to tell "entered"
        # from "never entered", and must stay a no-op in the second case.
        self._saved = None
        if root is not None:
            root = check_root(root)
        self._given_root = root

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in VARS}
        root = self._given_root or os.path.abspath(
            tempfile.mkdtemp(prefix="cckit-test-"))
        # The owner has a live assistant under the real ~/.cckit. Checked again
        # because the root may have come from mkdtemp — which reads the live
        # `tempfile.tempdir`, not our anchor — and always before the first
        # os.makedirs and before a single environment variable moves.
        try:
            self.root = check_root(root)
        except AssertionError:
            if self._given_root is None:
                # os.rmdir, not rmtree: mkdtemp leaves it empty, and a refused
                # root is the last place to start deleting recursively.
                try:
                    os.rmdir(root)
                except OSError:
                    pass
            self._saved = None
            raise
        self.home = os.path.join(self.root, "home")
        self.project = os.path.join(self.root, "project")
        self.bin = os.path.join(self.root, "bin")
        self.state = os.path.join(self.root, "state")

        for d in (self.home, self.project, self.bin, self.state):
            os.makedirs(d)

        os.environ["HOME"] = self.home
        os.environ["USERPROFILE"] = self.home
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.home, ".claude")
        os.environ["CCKIT_FAKE_STATE"] = self.state
        # Saved in VARS and dropped here: inherited from the owner's shell it
        # would point the installer's role library back out of the sandbox.
        # Gone, it falls back to ~/.cckit/library — inside this home.
        os.environ.pop("CCKIT_LIBRARY", None)
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
        self._install_fake()
        return self

    def _install_fake(self):
        fake = os.path.join(HERE, "fake_claude.py")
        sh = os.path.join(self.bin, "claude")
        with open(sh, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, fake))
        os.chmod(sh, os.stat(sh).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # On Windows the real `claude` is an npm shim named claude.cmd, so the
        # fake wears the same name. Nothing in subprocess finds it: CreateProcess
        # appends only '.exe' and never reads PATHEXT — `run_claude` resolves
        # the name through shutil.which, which does, and that is what makes this
        # file reachable there.
        with open(os.path.join(self.bin, "claude.cmd"), "w", encoding="utf-8") as fh:
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

    def __exit__(self, *exc):
        # Never entered — or entered and refused. Nothing was saved, so there
        # is nothing to restore and, above all, nothing to delete.
        if self._saved is None:
            return False
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._saved = None
        # The guard is the argument. Between __enter__ and here, self.root is
        # an ordinary attribute anyone can reassign, so the check that matters
        # is the one that cannot be walked around — the one inside the call.
        root = check_root(self.root)
        shutil.rmtree(root, ignore_errors=True)
        # ignore_errors swallows every failure: a root that is a symlink, a
        # permission error, a busy file. Silence there means directories pile
        # up under a green suite, so the result is checked, not assumed.
        if os.path.exists(root):
            raise AssertionError(
                "песочница не убрана: %s пережил rmtree — дерево осталось на "
                "диске, и следующий прогон начнётся не с чистого места" % root)
        return False
