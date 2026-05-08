---
name: review
description: Review recent code changes and suggest improvements
context: inline
user-invocable: true
when-to-use: When the user wants a quick code review of recent changes
---

# Code Review

1. Run `git diff` to see unstaged changes, or `git diff --cached` for staged changes.
2. Analyze the diff for:
   - Potential bugs or logic errors
   - Missing error handling
   - Style inconsistencies
   - Performance concerns
3. Provide a concise summary with specific, actionable suggestions.
4. Rate the overall change quality as Good, Needs Work, or Risky.

$ARGUMENTS
