# AGENT_FILES

Project documentation for agents and humans. Two layers:

- **`CARDS/`** — living docs (architecture, conventions, flows, testing, migrations, …). Start at [`CARDS/README.md`](CARDS/README.md) — it's a routing manifest with **Load when / Skip when** triggers per card.
- **Root files** — point-in-time snapshots and dated decision records, **not maintained** (kept as historical context — don't edit them to reflect current state; that's what `CARDS/` is for):
  - `AUDIT.md` — point-in-time security/codebase audit (14 findings).
  - `ASSESSMENT_CODE.md` — point-in-time module-by-module code assessment.
  - `SDK_BUMP_2026-06-03.md` — record of the `claude-agent-sdk` floor bump (>=0.2.88).
  - `EVAL_file_checkpointing_2026-06-03.md` — eval of SDK file checkpointing for review→reject (decision: no).
  - `PLAN_graphify_capability_2026-06-06.md` / `EVAL_graphify_capability_2026-06-06.md` — feasibility eval + implementation plan for the graphify knowledge-graph capability (now shipped; see `CARDS/GRAPHIFY.md`).
  - `PLAN_skills_library_2026-06-06.md` — implementation plan for the Agent-Skills library (now shipped; see `CARDS/SKILLS.md`).

If you're orienting on the project, go to `CARDS/` and ignore the root files unless you specifically need historical context.
