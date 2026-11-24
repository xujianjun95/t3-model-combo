---
name: t3-model-combo
description: Rank cost-effective 2-model or 3-model combinations from Artificial Analysis leaderboard across your enabled T3 Code providers, model creators, or custom provider groups using Intelligence Index and Cost per Task. Use when the user asks to compare model value combos, rank providers by cost-performance, save custom provider groups, or run /t3-model-combo.
---

# T3 Model Combo

Compare and rank cost-effective 2-model and 3-model combinations across your enabled T3 Code providers using Artificial Analysis Intelligence Index and Cost per Task benchmarks.

## End-to-End Workflow in T3 Code

Follow these steps whenever the user invokes `/t3-model-combo` or asks to compare model combinations, rank providers by value, or manage provider groups / golden combos.

### 1. Collect Current T3 Code Capabilities

Call `orchestrator_capabilities` to retrieve the user's currently enabled providers, instances, models, and options.

Save the full JSON response to a temporary file (e.g., `/tmp/t3-model-combo-caps.json`). Never fabricate or omit provider/model entries.

### 2. Locate Skill Directory & Render Interactive Widget

Locate `<skill_dir>` (the directory containing this `SKILL.md` and `scripts/build_widget.py`). Check in order:
1. Current workspace if `scripts/build_widget.py` exists there
2. `~/.agents/skills/t3-model-combo`
3. `~/.codex/skills/t3-model-combo`
4. `~/.claude/skills/t3-model-combo`
5. `~/.cursor/skills/t3-model-combo`
6. `~/.local/share/t3-model-combo`

Run the widget builder to generate a self-contained HTML file (e.g., `/tmp/t3-model-combo.rendered.html`):

```bash
python3 <skill_dir>/scripts/build_widget.py render \
  --capabilities-file /tmp/t3-model-combo-caps.json \
  --output /tmp/t3-model-combo.rendered.html
```

Pass optional flags based on the user's request:
- `--refresh` — force refresh cached Artificial Analysis leaderboard data
- `--mode <t3|creator|custom>` — comparison scope (`t3` enabled providers, `creator` model makers, or `custom` saved group)
- `--combo-size <2|3>` — rank 2-model or 3-model combinations
- `--preference <0-100>` — balance between intelligence (higher) and cost savings (lower), default `55`
- `--min-intelligence <num>` — minimum Intelligence Index threshold, default `35`
- `--max-budget <num|none>` — maximum Cost per Task budget threshold (USD)
- `--exclude-same-release` / `--no-exclude-same-release` — exclude or allow different reasoning tiers of the same model pairing together

(Run `python3 <skill_dir>/scripts/build_widget.py render --help` if you need exact option names or defaults.)

### 3. Preview & Render Inline in Chat

1. Call `html_preview` with `path="/tmp/t3-model-combo.rendered.html"` to inspect the rendered widget and read its `contentHeight`.
2. Call `html_render` with `path="/tmp/t3-model-combo.rendered.html"`, a concise `title`, and `height=<contentHeight>` (clamped to the valid `html_render` range of `80`–`2000`) to display the interactive leaderboard card inline.
3. In your reply, **do not** repeat the full tables or details already visible in the rendered widget. Give a crisp summary of the Top 1–3 recommended combos and any notable trade-offs.

### 4. Closed-Loop Follow-Up Actions

Handle follow-up requests directly using the matching tool or subcommand:

- **Save or delete a custom provider group**:
  - Save: `python3 <skill_dir>/scripts/build_widget.py group-save --name "<group_name>" --t3-provider-ids <id1,id2> --creators <c1,c2>`
  - List: `python3 <skill_dir>/scripts/build_widget.py group-list`
  - Delete: `python3 <skill_dir>/scripts/build_widget.py group-delete --id "<group_id>"`
  - After updating groups, re-render with `render --mode custom` -> `html_preview` -> `html_render` if the user wants to see the updated ranking.

- **Save a combination as a favorite / default golden combo**:
  - Save: `python3 <skill_dir>/scripts/build_widget.py favorite-save --name "<combo_name>" --model-ids <model_id_1> <model_id_2>`
  - List: `python3 <skill_dir>/scripts/build_widget.py favorite-list`
  - Delete: `python3 <skill_dir>/scripts/build_widget.py favorite-delete --id "<favorite_id>"`

- **Update persistent default preferences**:
  - Run: `python3 <skill_dir>/scripts/build_widget.py defaults-set --mode <t3|creator|custom> --combo-size <2|3> --preference <0-100> --min-intelligence <num> --max-budget <num|none>`

- **Switch the current thread to a chosen model**:
  - When the user picks a model from the leaderboard to use right now, call `t3_thread_configure` for the current thread with `modelSelection` populated from the matching `orchestrator_capabilities` entry (`provider`, `instanceId`, `model`, `options`).

- **Prioritize the user's golden combo when delegating subtasks**:
  - When the user asks to follow their default golden combo for subsequent `delegate_task` calls, read `~/.config/t3-model-combo/config.json` first and inspect `favoriteCombos` to select the configured models and providers.
