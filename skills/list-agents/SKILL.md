---
name: list-agents
description: Use when you want to know which assistants exist, where one lives, what it is allowed to do, who created it, or whether its fence was ever actually verified.
---

# Who is here

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py"
# короче, если установлен CCKit CLI: cckit assistant list          # this project (add --all for every project)
cckit assistant tree          # who created whom, with what capabilities
cckit assistant show <name>   # one instance in full
cckit assistant where <name> --path
```

`list` defaults to the project you are standing in and says how many it hid.
Assistants are bound to projects; a flat list mixes every project you ever
worked on.

## Read the "проверен" column

`НЕТ` means the fence was never proven — not that it is absent. An assistant
whose probe failed may be writing outside its area right now, because a
permission rule that matches nothing fails **open** and says nothing.

Fix it with `cckit assistant reset <name>`: everything generated is rebuilt from
the role, both probes re-run, and what the assistant earned — its memory,
`LEARNED.md`, the owner's rules — is kept.

## What `show` tells you that `list` does not

Where each setting came from: the access-class template, the grants given at
install, or an order from the owner. An owner's rule carries their words
verbatim, so a month later it reads as their decision rather than someone's
opinion.
