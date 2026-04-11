# Add Feature

Implement a new feature for the AI Stock Investment Recommender project.

**Feature request:** $ARGUMENTS

---

## Execution checklist

Work through each step in order. Do NOT skip any step.

### 1. Understand the codebase

Before writing any code, read the relevant files to understand how existing features are implemented. This project has three main Python files:

- `stock_analyser.py` — Streamlit app entry point: stock universe, indicators, scoring, UI rendering
- `portfolio_manager.py` — portfolio state, AI OCR, recommendations, Telegram formatting
- `daily_picks.py` — standalone Telegram digest script

Read whichever files are most relevant to the requested feature. Also read `CLAUDE.md` to confirm any project-specific constraints before starting.

### 2. Plan the implementation

Think through:

- Which file(s) need to change
- Whether any new dependencies are needed (add to `pyproject.toml` if so; use `uv add <pkg>`)
- Whether the feature touches `daily_picks.py` (which intentionally duplicates logic from `stock_analyser.py` — keep them in sync)
- Any secrets / config changes needed in `.streamlit/secrets.toml.example`

### 3. Implement the feature

Follow these project standards:

**Python style:**

- Type annotations on all function signatures
- `loguru` for logging (not stdlib `logging`)
- Pydantic v2 for any new data schemas
- Keep functions small and single-purpose; avoid deep nesting
- Format with `ruff` after writing (`ruff format <file>` and `ruff check --fix <file>`)

**Streamlit conventions:**

- Cache all network calls with `@st.cache_data(ttl=...)`
- All prices displayed to users must be in EUR; use the existing multiplier chain (`get_mult`)
- All timestamps use `Europe/Berlin` timezone via `ZoneInfo("Europe/Berlin")`
- Use `Styler.map()` for DataFrame cell styling (not deprecated `applymap`)

**Data / state:**

- `portfolio.json` is the persistence layer — if the feature needs new state, add a new top-level key
- Never break existing keys in `portfolio.json`

**Security:**

- No user-controlled data in log calls (bandit py/log-injection rule)
- No `eval`, `exec`, or shell injection vectors

### 4. Update CLAUDE.md

After implementing, update `CLAUDE.md` to reflect the new feature:

- Add or extend the **Architecture** section if new files or modules were created
- Add or extend any relevant section (e.g. secrets, running instructions, key data-flow notes)
- Keep entries concise — one paragraph or a short bullet list per feature

### 5. Update docs/index.md

Before committing, update `docs/index.md` (the project wiki / GitHub Pages site):

- Add a row to the **Features** table describing the new capability
- If the feature introduces new configuration keys, add them to the **Configuration** section
- If the architecture changes (new file, new component), update the **Architecture** diagram block
- If new dependencies were added, add a row to the **Technical Stack** table

### 6. Verify

- Run the app locally to confirm the feature works: `uv run streamlit run stock_analyser.py`
- If `daily_picks.py` was changed, run it in dry-run to check for errors: `python daily_picks.py` (no Telegram token → graceful failure is acceptable)
- Run `ruff check .` and fix any remaining lint issues

### 7. Commit

Stage only the files you changed (never `git add -A` blindly). Write a concise commit message in imperative mood explaining *why* the change was made, not what was changed.

```bash
git add <specific files>
git commit -m "feat: <short description of the feature>"
```

Never use `--no-verify`.
