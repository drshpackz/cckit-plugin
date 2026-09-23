"""A temporary home, a fake `claude` on PATH, and the guarantee that neither
outlives the test."""

import json
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VARS = ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "PATH", "CCKIT_FAKE_STATE",
        "CCKIT_LIBRARY")


def _real(p):
    return os.path.normcase(os.path.realpath(p))


def _same(a, b):
    return _real(a) == _real(b)


def _under(child, parent):
    return _real(child).startswith(_real(parent) + os.sep)


def check_root(root):
    """The one rule that decides what `__exit__` is allowed to delete.

    A white list, not a black one: the root MUST lie inside
    `tempfile.gettempdir()`. Listing dangerous roots instead — the real home,
    '/', its parent — is a game that ends one case short of safe every time;
    under this rule all three simply fail to be temporary. Strictly inside,
    so the temporary directory itself is not deletable either.

    Returns the root, or raises before anything has been created.
    """
    tmp = tempfile.gettempdir()
    if not _under(root, tmp):
        raise AssertionError(
            "корень песочницы отвергнут: %s — он не лежит внутри временного "
            "каталога %s, а удалять при выходе можно только там" % (root, tmp))

    # Redundant after the white list, and kept for the message rather than the
    # protection: "not a temporary directory" reads as a technicality, "this is
    # the real home" does not.
    real = os.path.expanduser("~")
    if _same(root, real) or _same(os.path.join(root, "home"), real):
        raise AssertionError(
            "корень песочницы отвергнут: %s — это настоящий дом %s" % (root, real))
    if _under(real, root):
        raise AssertionError(
            "корень песочницы отвергнут: %s — внутри него лежит настоящий дом "
            "%s, который выход стёр бы вместе с деревом" % (root, real))
    return root


class Sandbox(object):
    def __init__(self, root=None):
        """`root` exists only so the guard can be exercised by a test. Left at
        None — which is every real use — the root is a fresh temporary
        directory that cannot be anybody's home.

        The guard runs here, in the constructor: a refused root is refused
        before a single directory exists, so there is nothing to clean up and
        nothing for a broken guard to delete.
        """
        if root is not None:
            check_root(root)
        self._given_root = root

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in VARS}
        self.root = self._given_root or tempfile.mkdtemp(prefix="cckit-test-")
        # The owner has a live assistant under the real ~/.cckit. Checked again
        # because the root may have come from mkdtemp, and always before the
        # first os.makedirs and before a single environment variable moves.
        try:
            check_root(self.root)
        except AssertionError:
            if self._given_root is None:
                shutil.rmtree(self.root, ignore_errors=True)
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
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.root, ignore_errors=True)
        return False
