---
name: using-assistants
description: Use when work needs digging that outlives this conversation — reading a codebase you will read again, research you will need next week, or anything you are about to do by hand for the third time.
---

# You have assistants

An assistant is a separate, long-lived Claude session bound to one project,
with its own brain, its own memory, and a fence that was tested at install
time. It is not a subagent: it survives this conversation and keeps what it
learned.

**It works for you.** You brief it, you read what it produces, you replace it
when it stops earning its keep. Hand it the digging and keep building while it
digs — do not stop and ask permission for each task. Ask only where the cost
is one-sided: leaving the sandbox, spending past its ceiling, hiring a new one.

Reach for one when the work is **collecting**, not deciding — and when you will
want the result again. Do the deciding yourself.

| You want to | Load |
|---|---|
| make a new assistant | `cckit:create-agent` |
| see who serves this project | `cckit:list-agents` |
| find one someone published | `cckit:find-agent` |

Already installed? `cckit assistant list` shows who is here; give it work
directly. Keep doing it yourself when it is one question with one answer: an
assistant costs a cold start every time.
