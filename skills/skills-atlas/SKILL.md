---
name: skills-atlas
description: Start Skill Atlas, a local page that lists the agent skills on this machine, and print its URL.
disable-model-invocation: true
---

Run this one command with the Bash tool, and do nothing else:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/start-atlas.sh"
```

Then tell the user the URL that it prints. If it fails, show the last lines of its output. Do not
run other commands, and do not try to fix the error.
