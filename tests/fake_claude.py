#!/usr/bin/env python3
"""A `claude` that answers from a file and records how it was called.

It exists so the fence, the isolation and the install flow can be asserted
without a model, a network or a bill.
"""

import json
import os
import sys


def main():
    state = os.environ["CCKIT_FAKE_STATE"]
    reply = {"result": "", "session_id": "s1", "total_cost_usd": 0.0}
    rp = os.path.join(state, "reply.json")
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as fh:
            reply.update(json.load(fh))

    with open(os.path.join(state, "calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                             "env": dict(os.environ)}, ensure_ascii=False) + "\n")

    prompt = reply.pop("transcript_prompt", None)
    if prompt:
        d = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR",
                                        os.path.join(os.path.expanduser("~"), ".claude")),
                         "projects", "box")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, reply["session_id"] + ".jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "attachment", "attachment": {
                "type": "prompt_snapshot", "systemPrompt": [prompt]}}) + "\n")

    sys.stdout.write(json.dumps(reply, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
