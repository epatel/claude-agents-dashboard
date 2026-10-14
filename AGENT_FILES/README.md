# AGENT_FILES

Project documentation for agents and humans. Two layers:

- **`CARDS/`** — living docs (architecture, conventions, flows, testing, migrations, …). Start at [`CARDS/README.md`](CARDS/README.md) — it's a routing manifest with **Load when / Skip when** triggers per card. One further living reference sits outside this tree: [`docs/item-states.md`](../docs/item-states.md), the `ItemState` FSM.
- **Root files** — point-in-time snapshots and dated decision records, **not maintained** (kept as historical context — don't edit them to reflect current state; that's what `CARDS/` is for):
  - `AUDIT.md` — security audit, rev 14 (17 findings; **no actionable finding open** — 10 of 11 remediated and **#15 mitigated**). #15 (Kimi worktree confinement) denies out-of-worktree paths on every ACP permission request and logs the tool calls kimi never asks about — read its Residual-gap note before working on the Kimi runtime or the `--experimental` flag. Rev 14 closed #16: skill installs validate every remote tree path locally and cap each HTTP response.
  - `ASSESSMENT_CODE.md` — point-in-time module-by-module code assessment.
  - `SDK_BUMP_2026-06-03.md` — record of the `claude-agent-sdk` floor bump (>=0.2.88), plus a dated rev note per later floor bump (current floor: >=0.2.165).
  - `EVAL_file_checkpointing_2026-06-03.md` — eval of SDK file checkpointing for review→reject (decision: no).
  - `PLAN_graphify_capability_2026-06-06.md` / `EVAL_graphify_capability_2026-06-06.md` — feasibility eval + implementation plan for the graphify knowledge-graph capability (now shipped; see `CARDS/GRAPHIFY.md`).
  - `PLAN_skills_library_2026-06-06.md` — implementation plan for the Agent-Skills library (now shipped; see `CARDS/SKILLS.md`).

If you're orienting on the project, go to `CARDS/` and ignore the root files unless you specifically need historical context.
