# Agent Instructions

Read `CONTEXT.md` first in every session. It holds the current state and the decisions already made. Update it at the end of a session.

## Layers
- **Directives (`directives/`):** SOPs in Markdown that define what to do, inputs, tools and edge cases. Update them when you learn something (API limits, data quirks). Don't delete or overwrite one without asking.
- **Orchestration (you):** read the directive, run the tools in order, handle errors, ask when unclear.
- **Execution (`engine/`):** deterministic Python modules. Check `engine/` before writing new code; extend existing modules rather than adding one-off scripts.

## Layout
```
engine/config.py        every constant / exclusion / weight lives here
engine/sql/*.sql        one dataset per file, formatted with config.SQL_PARAMS
engine/build.py         entry point: python -m engine.build
engine/backtest.py      python -m engine.backtest
web/template.html       dashboard (data injected at __DATA__)
worker/, .github/       hosting + schedule (same pattern as ist/istengine)
docs/similarity_logic.md  FINAL similarity spec
```

## Rules
- Snowflake exclusions and category normalisation come only from `engine/config.py`. Never hard-code them in SQL.
- Never publish a `TW_FAKE_EMBED=1` build. `build.publish` refuses to, and that guard must stay.
- Secrets live only in GitHub Secrets / `.env`, never in code.
- When something breaks: fix it, test it (`python -m engine.build` with `TW_DEV_DATA`, then `node tests/smoke_dashboard.js index.html`), and record the learning in the directive.
