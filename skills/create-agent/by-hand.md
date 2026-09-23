# Building an assistant home by hand

For a machine with no Python. Every rule here was measured, and **each one fails
silently when you get it wrong** — that is why the installer exists.

Create `<home>` = `~/.cckit/assistants/<role>@<project-name>/`, **never inside
the project repository**: a home inside a repo inherits that repo's `CLAUDE.md`,
which the assistant must not follow.

## 1. `<home>/.claude/agents/<role>.md`

```
---
name: <role>
description: <one line>
memory: project
---

<the role body — this REPLACES Claude Code's system prompt>
```

Only those three keys are read. **A card missing `name:` is ignored entirely**:
the assistant answers normally, costs the same, and runs the stock prompt.
`appendSystemPrompt` is never parsed; `permissionMode` never reaches a `-p` run.

## 2. `<home>/.claude/settings.json`

```json
{
  "agent": "<role>",
  "model": "claude-opus-5",
  "modelSettings": { "claude-opus-5": { "effortLevel": "xhigh" } },
  "maxEffortLevel": "xhigh",
  "permissions": {
    "defaultMode": "default",
    "additionalDirectories": ["<project>"],
    "allow": [
      "Read(//<project>/**)",
      "Read(//<home>/**)",
      "Edit(//<home>/**)",
      "Edit(//<project>/<writable dir>/**)"
    ],
    "deny": ["Edit(//<project>/src/**)", "Bash"]
  },
  "claudeMdExcludes": ["<project>/CLAUDE.md", "<project>/.claude/CLAUDE.md"]
}
```

Five things that are silent when wrong:

- **Two slashes** after `(` for an absolute path. `Edit(/Users/…)` matches nothing.
- **No bare tool names** in `allow`. `"Read"` grants the whole filesystem.
- `defaultMode` is `default`, not `acceptEdits` — that accepts whatever is not denied.
- `effortLevel` stops at `xhigh`; `max` goes in `maxEffortLevel` only.
- One invalid value anywhere makes `-p` **discard this whole file**.

## 3. Trust, or none of the above applies

In `~/.claude.json` set `projects["<home>"].hasTrustDialogAccepted = true` and
the same for `<project>`. Until then every `allow` rule and
`additionalDirectories` is ignored, with no message.

## 4. Run it isolated

Remove these from the environment before launching:
`CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN`,
`CLAUDE_CODE_SESSION_ID`, `CLAUDE_PID`, `CLAUDE_CODE_CHILD_SESSION`,
`CLAUDE_CODE_SESSION_ATTENDED`, `CLAUDE_CODE_ENTRYPOINT`. Set
`CLAUDE_CODE_HARBOR_KITE=0`. Add `--strict-mcp-config` and
`--disallowedTools SendMessage ListAgents Monitor RemoteTrigger`.

Without this the assistant joins the owner's session network, sees every live
session and can write to them unasked. Removing the built-in tools alone is not
enough: an MCP server offers the same thing from the other side.

## 5. Prove both, before you trust it

**The fence:** ask it to write into a denied directory, then look at the disk.
Its own account of what happened is not evidence.

**The brain:** find the session transcript under `~/.claude/projects/`, take the
record whose `attachment.type` is `prompt_snapshot`, and check that
`systemPrompt[0]` starts with the role body. Anything after it must be the
`# Persistent Agent Memory` block and nothing else.

If you skip step 5 you do not have an assistant. You have a hope.
