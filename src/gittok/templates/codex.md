# GitTok in Codex

Session notes for Codex. Each GitTok skill in `.agents/skills/` holds its full
workflow and ends with "In Codex": how to start a worker, run a skill or a shell
command, and make images here. The workers' instructions are in `.agents/workers/`.
Paths are relative to the GitTok directory.

## Connection

`.codex/config.toml` starts `gittok mcp --ui` over stdio and with it the feed
server (in a clone through `uv run`). If the GitTok tools are missing, check
`/mcp` and whether this project's configuration is trusted. After an MCP or
server setting changes, restart the Codex session. `gittok init <dir>` makes a
GitTok directory.

The MCP launch sets `GITTOK_AGENT=codex`. With `render.image_backend: auto`, this
makes agent images the default here; `agent.models.codex` in `local/settings.yaml`
names the worker models (none: the session's model).

## Startup and keeping the feed full

`.codex/hooks.json` supplies the SessionStart hints. Review
and trust these local hooks with `/hooks`. If hooks did not print hints, run
`gittok url --hint`, `gittok health --hint`, and `gittok feed-watch --hint` once
at the first turn (prefix each with `uv run --quiet` in a clone). Give the feed
address from the url hint in the first reply (the phone address; the computer address
only when phone access is off). Follow the health hints, using the Codex skills.

For the feed-watch hint, start the Codex variant with the shell tool's
background/yield mechanism, once per session:

- GitTok directory: `gittok feed-watch --codex-thread "$CODEX_THREAD_ID"`
- Source clone: `uv run --quiet gittok feed-watch --codex-thread "$CODEX_THREAD_ID"`

Check that `CODEX_THREAD_ID` is nonempty and that `codex queue --help` supports
`--resume` before starting this variant. It waits for a refill signal, then runs
`codex queue --thread <id> --message <refill prompt> --resume` against the local
Codex daemon. This requests a new turn in this same thread even while idle;
it does not rely on the client delivering shell completion notifications.
Keep its process handle; do not detach it with `nohup` or start a second watch.
On a queued refill prompt, run `$gittok-generate` and restart this Codex watch.
Do not also generate merely because the watch exited successfully: its queued
prompt owns that refill. Delivery receipts under `data/codex-wake/` prevent the
same signal from being queued again to this thread when the watch restarts.
The normal `get_brief` need and run limits still apply.

Queue success does not prove resume succeeded: the Codex CLI can exit zero with
a resume warning. Inspect stdout and stderr when the watch completes. If queueing
fails or resume warns, report the limitation and check `feed_health` on the next
user turn. Do not repeatedly requeue the same request. Without a thread id,
`codex queue --resume`, or a reachable local daemon, use the plain watch and this
per-turn fallback; do not promise idle refill. Do not wait forever at the end of a turn.
