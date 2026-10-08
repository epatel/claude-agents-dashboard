---
name: files-skill
description: Analyze an existing codebase and produce a compact, agent-ready conventions document (CLAUDE.md / AGENTS.md) that captures structure, naming, idioms, and — critically — internal contradictions classified as canonical, aspirational, or legacy. Use this whenever the user wants to onboard an agent to a codebase, set up or refresh a CLAUDE.md / AGENTS.md, audit code style across a project, surface inconsistencies between modules, or prepare a project for AI-assisted development. Trigger this even when the goal is described indirectly — e.g., "help my agent understand my project," "what conventions does this code follow," "why isn't my agent matching our style," "we have inconsistent patterns across modules," or "I want to write a style guide based on what we actually do." Do not skip the interactive triage step: contradictions in real codebases are signals, not noise, and only the human can classify them.
---

# Codebase Conventions Distiller

Produce a small, evidence-backed conventions document that an LLM agent can load into context to write code that matches the project's actual style — not the model's priors.

## Philosophy

A real codebase is never internally consistent. Different modules use different patterns; the team has opinions about which are "right" that aren't visible from the code alone. A naive analyser averages frequencies and produces a style guide that pretends consistency exists. That artifact is worse than nothing: it gives the model authoritative-looking misinformation.

The useful framing is that **contradictions are backlog**. Where the codebase has competing patterns, that's a question, not an answer. The team has a current state and a target state, and the delta is the migration work. The skill's job is to surface the contradictions, ask the human which way is canonical, and produce a layered output that distinguishes:

- **Canonical** — patterns that are both current practice and aspiration. Agents follow these unconditionally.
- **Aspirational** — the direction the team is moving. Agents follow these for new code; existing code may not match yet.
- **Legacy** — patterns present in the codebase that should not be extended. Agents need to recognize these (so they understand what they're reading) but never produce them.

The output is the doc. The skill does not rewrite code, enforce style, or run linters. Those are separate jobs.

## Hard constraints

These are not preferences; they are the difference between a useful artifact and a harmful one.

- **Size cap on the primary output.** The agent-facing `CLAUDE.md` (or `AGENTS.md`) must stay under ~3–5k tokens. If it's bigger than the files the agent would have read anyway, the skill failed. Detail goes in the secondary artifact, not the primary one.
- **Every claim is evidence-backed.** No vibes. "Code is generally clean" is forbidden. Each convention statement cites at least one example file and, where relevant, frequency counts ("47 of 53 service files do X").
- **Sample, don't enumerate.** Don't read the whole codebase. Pick representative files and read those. Reading everything pushes the analysis itself into the dumb zone.
- **Never rewrite or "fix" code.** Read-only operation. The output is documentation.
- **Do not invent conventions the codebase doesn't show.** If the project has no testing convention, say so — don't fabricate one.
- **Idempotent and diff-able.** The same codebase should produce roughly the same output across runs, and re-runs should be diffable against prior outputs to show migration progress.

## Phases

Walk through these in order. Don't skip phase 5 (the interactive query); it is what makes this skill useful rather than a frequency report.

### Phase 1 — Scan

Goal: figure out what kind of project this is before reading any source.

- Identify languages and frameworks. Look at manifest files (`package.json`, `pyproject.toml`, `Cargo.toml`, `pubspec.yaml`, `go.mod`, etc.), top-level directory names, and file extension counts.
- Identify entry points (main files, app roots, library exports).
- Identify the test setup (test directories, test runner config, naming patterns of test files).
- Identify build/CI config (briefly — for context, not for deep analysis).
- Note repository size: total file count, source file count, lines of code per language (rough order of magnitude).

Output of this phase is internal state, not user-facing.

### Phase 2 — Sample

Goal: pick a small set of files that are representative of how the team actually writes code.

Use a mix of strategies:

- **Entry points** — the main app file, public API surface of each top-level module.
- **Recently-modified files** — what does new code look like? (Use git log if available.)
- **High-fanout files** — files with many dependents are likely canonical examples of how to write that layer.
- **One file per architectural layer** — model, view, service, repository, controller, route, etc., depending on the project shape.
- **A few test files** — to cover testing conventions.

Cap the sample. For a small project, 10–15 files is plenty. For a large monorepo, 25–40. Reading more is rarely worth the attention cost.

If the codebase is very large, consider doing this phase as a subagent with its own context, returning only the file list and a one-line rationale for each pick.

### Phase 3 — Extract conventions

Goal: from the sampled files, populate a checklist of convention areas.

Use the universal checklist in `references/checklist.md`. The checklist is language-agnostic in structure — concerns like "naming," "error handling," "file organization" apply to most projects — but interpret each item in the conventions of the actual language. Skip items that don't apply.

For each checklist item, record:
- The pattern observed (concrete and specific — "async functions are named `fetchX` for network, `loadX` for cache-or-network").
- Frequency / scope ("17 of 19 sampled service files," "all repository files," "all tests but `auth_legacy_test.dart`").
- One or two example file references with line numbers.
- Whether the pattern is uniform or shows competing variants. If competing, list each variant with its own count.

Items where competing variants exist feed directly into Phase 4.

### Phase 4 — Detect contradictions

Goal: produce an explicit list of places where the codebase shows competing patterns for the same concern.

Each contradiction is a structured record:

```
Concern: <what the contradiction is about, e.g., "state management approach">
Variants:
  A: <pattern>, found in <count> files, examples: <paths>
  B: <pattern>, found in <count> files, examples: <paths>
  (etc.)
Heuristic guess: <if signals exist — recency, file modification times, comments — name the likely canonical one, but mark it as a guess>
```

Do not try to resolve contradictions automatically. The whole point of the next phase is that only the human can do this.

### Phase 5 — Query the human

This is the load-bearing step. Skipping or short-circuiting it produces the bad averaged-frequencies output.

Present the contradictions list to the user, one item or small group at a time, and ask for triage. For each contradiction, the user picks:
- Which variant is **canonical** (the one new code should use).
- Which variants are **legacy** (recognized but not extended).
- Whether any variant is **aspirational** but not yet dominant in the code.

Use structured options where possible — the question bank in `references/question-bank.md` has templates. Mobile-friendly tappable options beat free-text wherever the choice is enumerable.

Also ask the higher-level direction questions:

- For each convention area where the codebase is *silent* (no clear pattern): is that intentional, or is there a target convention the team wants to start applying? (e.g., "you have no consistent error handling pattern — is that aspirational?")
- Are there hidden conventions the analysis can't see? Things like "we never use library X even though it would work" or "we always prefer composition over inheritance" that aren't visible from a sample.
- Is there a known migration in flight that the agent should know about? ("We're moving from Provider to Riverpod" — this turns Provider usage from "current convention" into "legacy, don't extend.")

Record the user's answers verbatim in the synthesis input.

### Phase 6 — Synthesize

Produce two artifacts:

**Primary: `CLAUDE.md` (or `AGENTS.md` if user prefers)**

The small, agent-facing document. Hard cap ~3–5k tokens. Use the template in `references/output-templates.md`. Structure:

1. **Project shape** (one short paragraph) — what this codebase is, languages, top-level architecture.
2. **Canonical conventions** — the rules new code follows. Concrete and example-anchored. Each rule names an exemplar file the agent can read for reference.
3. **Aspirational conventions** — direction-of-travel rules. Marked clearly as aspirational, with a note that existing code may not match.
4. **Legacy patterns to recognize but not extend** — short, explicit. "If you see X in older modules, do not add new usage. If you are touching a legacy file anyway, consider migrating it."
5. **Pointers** — where to find canonical examples for each architectural layer. Two or three exemplar file paths, no more.

The agent loads this file into context. It should not read the whole document tree to figure out conventions; that's the whole point.

**Secondary: `CONVENTIONS_ANALYSIS.md`**

The longer artifact. Not loaded by the agent by default; for human reference and for diffing on future runs. Include:

- Sample list (which files were read in Phase 2 and why).
- Full convention extraction with frequencies and examples.
- Full contradictions list with the user's triage decisions recorded against each.
- Open questions the user deferred or marked uncertain.
- Run timestamp.

This is the artifact future runs of the skill diff against to surface migration progress.

### Phase 7 — Verify

Goal: catch cases where the synthesis is wrong before handing it to the user.

Pick two or three files that were *not* in the Phase 2 sample. Read them. For each canonical convention in the synthesized output, check whether the unseen files actually follow it. If they don't, that convention's claim is shakier than the sample suggested — flag it for the user.

This step catches over-generalization from a small sample. Don't skip it.

## Output handling

Save both artifacts in the project root by default, unless the user has indicated they keep agent docs elsewhere. Ask if unsure.

If the project already has a `CLAUDE.md` / `AGENTS.md`:
- Don't overwrite silently.
- Show the diff and ask before replacing.
- If the existing file has hand-curated content the analysis didn't generate, preserve it in a clearly-marked section.

## Re-running the skill

When the user invokes this skill on a codebase that already has a `CONVENTIONS_ANALYSIS.md` from a prior run, the skill should:

1. Read the prior analysis.
2. Run phases 1–4 fresh.
3. **Diff** the new findings against the prior:
   - New conventions detected.
   - Conventions that have changed frequency (especially: legacy patterns shrinking → migration progress).
   - New contradictions (or old ones that resolved).
4. In Phase 5, ask only about the *changes*, not every contradiction from scratch. The user already triaged the old ones.
5. In Phase 6, regenerate the artifacts and include a "Changes since last run" section in `CONVENTIONS_ANALYSIS.md`.

This is what makes the skill useful as ongoing migration radar rather than a one-shot tool.

## What this skill does not do

- It does not run linters or formatters.
- It does not modify any source code.
- It does not enforce conventions at commit time (that's a hook / CI job).
- It does not generate code in the project's style. Agents do that, using the artifact this skill produces.
- It does not replace human-curated architectural decision records (ADRs). It complements them.

## When the codebase is unsuitable

Some codebases shouldn't be run through this skill — say so and stop:

- Very small projects (< ~20 source files). The model can just read them.
- Single-file scripts or notebooks.
- Codebases where the user is the sole author and has the conventions in their head — usually a quick conversation produces a better doc than analysis.
- Greenfield projects with no committed code yet — there are no conventions to distill. Offer to help draft an aspirational `CLAUDE.md` from scratch instead.

## References

- `references/checklist.md` — universal convention checklist used in Phase 3.
- `references/question-bank.md` — question templates for Phase 5.
- `references/output-templates.md` — concrete templates for the two output artifacts.
