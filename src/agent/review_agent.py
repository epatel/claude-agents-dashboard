"""Auto-review agent — a separate Claude call that evaluates a completed task.

Used by the auto-approve workflow: after the main task agent finishes, this
module spins up a short-lived, read-only Claude session that inspects the
diff, the agent's last message, and (if needed) files in the worktree, then
emits a structured DECISION block. WorkflowService parses that decision and
either approves the item or sends comments back to the main agent.

The reviewer is intentionally restricted to Read/Glob/Grep — it must never
edit files or run shell commands. Cycle bookkeeping (max 3 retries) lives in
WorkflowService, not here; this module is a pure stateless review call.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
)

logger = logging.getLogger(__name__)


# Hard cap on diff size embedded in the prompt — anything larger gets
# truncated. The reviewer can still Read/Grep individual files in the
# worktree if it needs more context.
_MAX_DIFF_CHARS = 60_000

# Tools the reviewer is allowed to use. Strictly read-only — Edit/Write/Bash
# are denied. The agent inspects the diff in the prompt and may consult
# files in the worktree via Read/Glob/Grep.
_REVIEWER_ALLOWED_TOOLS = {"Read", "Glob", "Grep"}

_REVIEW_SYSTEM_PROMPT = """You are an automated code reviewer.

Inputs you will receive:
- A task description
- The implementing agent's final message
- The git diff of the work performed

Your job: decide whether the diff correctly and completely addresses the
task. You MAY use the Read/Glob/Grep tools to inspect files in the worktree
when the diff alone is ambiguous. You MUST NOT modify anything.

Be strict but fair:
- Approve when the work is correct, complete, and matches the task intent.
- Request changes when there are real problems: bugs, missing pieces,
  failures to follow the task description, or obvious quality issues.
- Don't request stylistic nitpicks; focus on correctness and completeness.

End your response with EXACTLY one of these decision blocks (and nothing
after it):

DECISION: APPROVED
SUMMARY: <one-line summary of why it's good>

— OR —

DECISION: CHANGES_REQUESTED
COMMENTS:
- <specific, actionable comment>
- <another specific comment>

Use bullet items starting with "- " for each comment. Be concrete: tell the
implementing agent exactly what to fix."""


_DECISION_RE = re.compile(r"DECISION:\s*(APPROVED|CHANGES_REQUESTED)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+)", re.IGNORECASE)


async def _review_can_use_tool(tool_name: str, *_args) -> object:
    """Strict allowlist for the review agent — read-only inspection only."""
    if tool_name in _REVIEWER_ALLOWED_TOOLS:
        return PermissionResultAllow()
    return PermissionResultDeny()


def _build_review_prompt(
    item_title: str,
    item_description: str,
    diff: str,
    last_message: str,
) -> str:
    if len(diff) > _MAX_DIFF_CHARS:
        diff_text = (
            diff[:_MAX_DIFF_CHARS]
            + f"\n\n... [diff truncated; original was {len(diff)} chars; "
            "use Read/Grep on worktree files for missing context]"
        )
    else:
        diff_text = diff or "(no diff produced)"

    last_msg_text = last_message.strip() if last_message else "(agent did not leave a final message)"

    return (
        f"# Task\n{item_title}\n\n{item_description or '(no description)'}\n\n"
        f"# Implementing agent's final message\n{last_msg_text}\n\n"
        f"# Diff\n```diff\n{diff_text}\n```\n\n"
        "Review the diff against the task. Consult worktree files with "
        "Read/Glob/Grep if the diff alone is unclear. Then output your "
        "DECISION block exactly as specified by the system prompt."
    )


async def run_auto_review(
    *,
    worktree_path: Path,
    model: str | None,
    item_title: str,
    item_description: str,
    diff: str,
    last_message: str,
    ollama_env: dict[str, str] | None = None,
    timeout: float = 240.0,
) -> dict:
    """Run a one-shot review agent and parse its decision.

    Returns a dict with keys:
        approved: bool
        comments: list[str]   # actionable comments (only when not approved)
        summary:  str         # short rationale (only when approved)
        raw:      str         # full agent text, useful for logging
    """
    prompt = _build_review_prompt(item_title, item_description, diff, last_message)

    is_ollama = bool(ollama_env)
    if is_ollama:
        options = ClaudeAgentOptions(
            cwd=worktree_path,
            system_prompt=_REVIEW_SYSTEM_PROMPT,
            model=model,
            permission_mode="bypassPermissions",
            allowed_tools=list(_REVIEWER_ALLOWED_TOOLS),
            can_use_tool=_review_can_use_tool,
            add_dirs=[str(worktree_path)],
            env=ollama_env,
        )
    else:
        options = ClaudeAgentOptions(
            cwd=worktree_path,
            system_prompt=_REVIEW_SYSTEM_PROMPT,
            model=model,
            permission_mode="bypassPermissions",
            allowed_tools=list(_REVIEWER_ALLOWED_TOOLS),
            can_use_tool=_review_can_use_tool,
            add_dirs=[str(worktree_path)],
            env={},
        )

    client = ClaudeSDKClient(options=options)
    chunks: list[str] = []
    try:
        await client.connect()
        await client.query(prompt)
        try:
            async with asyncio.timeout(timeout):
                async for message in client.receive_messages():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text:
                                chunks.append(block.text)
                    elif isinstance(message, ResultMessage):
                        break
        except asyncio.TimeoutError:
            logger.warning(
                "Auto-review timed out after %.0fs for task %r",
                timeout,
                item_title,
            )
    except Exception as e:
        logger.exception("Auto-review session failed: %s", e)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    raw = "\n".join(chunks).strip()
    return _parse_decision(raw)


def _parse_decision(raw: str) -> dict:
    """Translate the reviewer's free-form text into a structured decision.

    If the reviewer didn't produce a parseable DECISION block we conservatively
    default to changes_requested with a placeholder comment, so the workflow
    doesn't silently merge unreviewed work.
    """
    if not raw:
        return {
            "approved": False,
            "comments": ["Auto-review produced no output."],
            "summary": "",
            "raw": "",
        }

    m = _DECISION_RE.search(raw)
    if not m:
        return {
            "approved": False,
            "comments": [
                "Auto-review did not emit a DECISION block; defaulting to "
                "changes_requested. Reviewer output: "
                + (raw[:500] + ("…" if len(raw) > 500 else ""))
            ],
            "summary": "",
            "raw": raw,
        }

    decision = m.group(1).upper()
    if decision == "APPROVED":
        sm = _SUMMARY_RE.search(raw)
        summary = sm.group(1).strip() if sm else ""
        return {"approved": True, "comments": [], "summary": summary, "raw": raw}

    # CHANGES_REQUESTED — gather bullet comments under the COMMENTS: header.
    comments: list[str] = []
    in_comments = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not in_comments:
            if stripped.upper().startswith("COMMENTS:"):
                in_comments = True
            continue
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ", "• ")):
            comments.append(stripped[2:].strip())
        elif comments:
            # Continuation of the previous bullet.
            comments[-1] = (comments[-1] + " " + stripped).strip()

    if not comments:
        comments = [
            "Auto-reviewer requested changes but did not provide specific comments."
        ]

    return {"approved": False, "comments": comments, "summary": "", "raw": raw}
