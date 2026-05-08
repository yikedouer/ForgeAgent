---
name: commit
description: Create a git commit with an auto-generated message
context: inline
user-invocable: true
when-to-use: When the user wants to commit staged changes with a good message
---

# Auto Commit

1. Run `git diff --staged` and `git status` to see what's staged.
2. If nothing is staged, tell the user to stage files first.
3. Write a concise, conventional commit message summarizing the changes.
4. Execute `git commit -m "<message>"`.

If the user provides additional context, incorporate it into the commit message.

$ARGUMENTS
