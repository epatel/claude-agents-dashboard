---
name: debug
description: Use when fixing a bug, investigating a failure, or troubleshooting unexpected behavior. Enforces root-cause investigation before any fix attempt.
version: 1.0.0
---

# Debug

Find root cause before fixing. No guessing.

## The Rule

**Do not attempt a fix until you understand why it's broken.** If you haven't read the error, reproduced it, and traced the cause — you're guessing.

## Process

### 1. Investigate

- **Read the error.** Full stack trace, line numbers, error codes. The answer is often right there.
- **Reproduce it.** Can you trigger it reliably? If not, gather more data.
- **Check what changed.** Git diff, recent commits, new dependencies.
- **Trace the data.** Where does the bad value come from? Follow it backward to the source.

If the task description includes an error message or log, start there. If not, use `ask_user` to get the exact error.

### 2. Find the Pattern

- Find similar **working** code in the codebase
- Compare working vs. broken — list every difference
- Don't assume any difference "can't matter"

### 3. Hypothesize and Test

- State your hypothesis: "X is broken because Y"
- Make the **smallest** possible change to test it
- One variable at a time — never bundle multiple fixes
- If it didn't work, form a **new** hypothesis (don't pile on more changes)

### 4. Fix

- Write a failing test that reproduces the bug
- Implement the single fix for the root cause
- Verify: test passes, no other tests broken
- Set commit message explaining the root cause and fix

### 5. If Stuck After 3 Attempts

Stop. Use `ask_user` to explain:
- What you investigated
- What you tried and why it didn't work
- What you think the underlying issue might be

Three failed fixes usually means an architectural issue, not a code issue.

## Red Flags

If you catch yourself thinking any of these, stop and go back to step 1:

- "Quick fix, investigate later"
- "Just try changing X"
- "I don't fully understand but this might work"
- "Let me fix multiple things at once"
