# Add Feature

Implement the requested feature: **$ARGUMENTS**

## Steps — follow in order, skip none

### 1. Feature branch

```bash
git fetch origin && git checkout master && git pull origin master
git checkout -b feats/<ticket-if-any>-<concised-name>
```

Branch: `feats/PROJ-42-ai-signals` (with ticket) or `feats/ai-signals` (without).
Ticket = any `PROJ-123`, `#42`, `GH-7` found in `$ARGUMENTS`. Name ≤ 4 words, hyphens only.

### 2. Read before writing

Read relevant files + `CLAUDE.md`. Key files: `stock_analyser.py`, `portfolio_manager.py`, `daily_picks.py`.

### 3. Plan

- Which files change? New deps (`uv add`)? `daily_picks.py` in sync? Secrets changes?

### 4. Implement

- Type annotations · `loguru` logging · Pydantic v2 schemas · `ruff format` + `ruff check --fix`
- `@st.cache_data(ttl=...)` on all network calls · prices in EUR via `get_mult` · Berlin timezone
- `portfolio.json` for new state (never break existing keys) · no eval/exec/log-injection

### 5. Update docs

- `CLAUDE.md` — architecture section if new files/modules added
- `docs/index.md` — Features table row, Configuration keys, Architecture block, Tech Stack row

### 6. Verify

```bash
uv run streamlit run stock_analyser.py   # confirm feature works
python daily_picks.py                    # graceful failure OK if no Telegram token
ruff check .                             # fix any remaining issues
```

### 7. Human review — STOP and wait for approval

Start the app and hand control to the user:

```bash
uv run streamlit run stock_analyser.py
```

Then say exactly:
> **The app is running at <http://localhost:8501>. Please test the feature and let me know:**
>
> - Approve → I'll commit and wrap up
> - Request changes → describe what to fix and I'll iterate from step 4

**Do not commit until the user explicitly approves.** If changes are requested, fix them and return to this step.

### 8. Commit (only after human approval)

```bash
git add <specific files>   # never git add -A
git commit -m "feat: <why, not what>"
```

Never `--no-verify`.
