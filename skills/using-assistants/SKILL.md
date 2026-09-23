---
name: using-assistants
description: Use when work needs digging that outlives this conversation — a codebase you will read again, research you will need next week, or anything you are about to do by hand a third time.
---

# You have assistants

An assistant is a separate, long-lived Claude session bound to one project,
with its own memory and a fence tested at install. Not a subagent: it outlives
this conversation and keeps what it learned.

**It works for you.** Hand it the work that is **collecting** — a codebase to
map, research to file — and keep building while it digs. Do the deciding
yourself. Brief it, read its output, replace it when it stops earning its keep,
and do not ask permission for each task: ask only where the cost is one-sided —
leaving the sandbox, overspending, hiring a new one.

| You want to | Load |
|---|---|
| make a new assistant | `cckit:create-agent` |
| see who serves this project | `cckit:list-agents` |
| find one someone published | `cckit:find-agent` |

`cckit assistant list` shows who is here. Do it yourself when it is one
question, one answer: an assistant costs a cold start.
