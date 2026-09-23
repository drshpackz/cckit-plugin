"""A temporary home, a fake `claude` on PATH, and the guarantee that neither
outlives the test."""

import json
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VARS = ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR", "PATH", "CCKIT_FAKE_STATE")


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def _same(a, b):
    return _norm(a) == _norm(b)


def _under(child, parent):
    return _norm(child).startswith(_norm(parent) + os.sep)


class Sandbox(object):
    def __init__(self, root=None):
        """`root` exists only so the guard in `__enter__` can be exercised by a
        test. Left at None — which is every real use — the root is a fresh
        temporary directory that cannot be anybody's home."""
        self._given_root = root

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in VARS}
        real = os.path.expanduser("~")
        self.root = self._given_root or tempfile.mkdtemp(prefix="cckit-test-")
        self.home = os.path.join(self.root, "home")
        self.project = os.path.join(self.root, "project")
        self.bin = os.path.join(self.root, "bin")
        self.state = os.path.join(self.root, "state")

        # The owner has a live assistant under the real ~/.cckit. Two ways the
        # suite could reach it: HOME pointed at it, or it sitting inside the
        # tree __exit__ deletes. Refused before a single directory is created.
        if _same(self.home, real) or _under(real, self.root):
            if self._given_root is None:
                shutil.rmtree(self.root, ignore_errors=True)
            raise AssertionError("песочница совпала с настоящим домом: %s" % real)

        for d in (self.home, self.project, self.bin, self.state):
            os.makedirs(d)

        os.environ["HOME"] = self.home
        os.environ["USERPROFILE"] = self.home
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.home, ".claude")
        os.environ["CCKIT_FAKE_STATE"] = self.state
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
        self._install_fake()
        return self

    def _install_fake(self):
        fake = os.path.join(HERE, "fake_claude.py")
        sh = os.path.join(self.bin, "claude")
        with open(sh, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, fake))
        os.chmod(sh, os.stat(sh).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # PATHEXT makes `claude` resolve to claude.cmd on Windows.
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
