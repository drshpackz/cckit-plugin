---
name: using-assistants
description: Use when work needs digging that outlives this conversation — reading a codebase you will read again, research you will need next week, or anything you are about to do by hand for the third time.
---

# You have assistants

An assistant is a separate, long-lived Claude session bound to one project. It
has its own brain, its own memory, and a fence that was tested at install time.
It is not a subagent: it survives this conversation and keeps what it learned.

Reach for one when the work is **collecting**, not deciding — and when you will
want the result again. Do the deciding yourself.

| You want to | Load |
|---|---|
| make a new assistant | `cckit:create-agent` |
| see who serves this project | `cckit:list-agents` |
| find one someone already published | `cckit:find-agent` |

Already installed? Give it work directly — `cckit assistant list` (или `python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py" list`) shows who is
here. Keep doing the work yourself when it is a single question with a single
answer: an assistant costs a cold start every time.
