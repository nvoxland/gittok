---
name: codescroll-generate
description: Generate new CodeScroll feed cards from the configured repos. Use when the user asks to generate, make, or refresh CodeScroll cards or the feed. Optional args - repo name and card count, e.g. "storefront 10".
model: sonnet
---

# Generate CodeScroll cards

You are the **driver**. You orchestrate; cheap subagents do the research and writing. Keep your own token use small: you never read repo files yourself.

Requires the `codescroll` MCP server (tools named `mcp__codescroll__*`). If those tools are missing, tell the user to start `uv run codescroll serve` in the CodeScroll repo and restart the session, then stop.

## Steps

1. **Get the brief.** Call `get_brief` with `repo` and `count` if the user gave them (default count comes from settings; never ask for more than 20 unless the user explicitly asks). Keep `run_id`, `guidance_markdown`, and `packets`. Do not call `get_brief` again in this run.

2. **Launch one subagent per packet**, up to 4 at a time, as parallel Agent calls **in one message, in the foreground** (do not set `run_in_background`). Foreground calls return in this same turn, so the whole run stays on this skill's model. Background hand-backs start new turns on the session model, which can be Opus.
   - `subagent_type`: `general-purpose`
   - `model`: the packet's `suggested_model` (`haiku` or `sonnet`). **Never use opus** unless the user asked for it in this request.
   - `prompt`: the packet's section from `brief_markdown` (its id, repo, count, story types, tones, personas, leads), then the full `guidance_markdown`, then: "run_id: <run_id>. Pass it to every mcp__codescroll__ research tool call. Return only a JSON array of exactly N card objects. Use only the mcp__codescroll__ research tools, at most 6 calls per card."

3. **Submit each packet's cards** as soon as its subagent returns: `submit_cards(run_id, cards)`. If the reply is not a JSON array, extract the array; if there is none, count the packet as empty.

4. **One fix round.** If `submit_cards` rejected cards, send the rejected cards with their `reason` and `detail` back to the **same subagent** and ask for corrected cards only. Use SendMessage and wait for its reply in this turn. Submit the corrections once. Drop anything still rejected. Do not do a second round.

5. **Stop early** when `totals.remaining` reaches 0. Do not launch more packets.

6. **Finish.** Call `finish_run(run_id, notes)` with `notes = {"models": {"<packet id>": "<model>"}, "driver_model": "<your model>", "empty_packets": [...]}`.

7. **Report** to the user in a few lines: cards accepted vs requested, the top reject reasons from `finish_run`, and that the feed is at http://127.0.0.1:8008.

## Rules

- You never research repos yourself. If a packet comes back empty, do not redo it; mention it in the report.
- Never invent or edit commits, paths, or line numbers in subagent output. The server checks them against git.
- This skill runs on Sonnet (`model: sonnet` in the frontmatter), whatever the session model is. The session model comes back after this turn. Only change that line if the user asks for a different driver.
