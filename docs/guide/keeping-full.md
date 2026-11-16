# Keep the feed full

An agent session (Claude Code or Codex) writes the cards. GitTok never starts a model by itself. So new cards come while a session is open in your GitTok directory.

## By itself

When a session starts, it also starts a **feed watch** in the background. The feed server tells the watch when the unread cards are running low (they will not last 3 days at your reading speed), or when you reached the end of the feed. Your agent then makes a batch of cards, and starts the watch again.

- It makes at most 10 runs a day, and it waits a few hours between runs.
- When you reach the end of the feed, it does not wait: the end-of-feed card says that new cards are being made.
- With no session open, nothing makes cards. The next session that starts answers at once.

## When you ask

> Make more cards.

> Make 10 cards about storefront.

Or type `/gittok-generate`. This always works.

## What a run costs

A run uses your model quota. It uses one writer worker for each small packet of cards (2 by default). A packet of simple formats needs only a `light` model, the rest a `standard` one. In Claude Code these are Haiku and Sonnet. In Codex, workers use your session's model until you name Codex models for the tiers (`agent.models` in [Configuration](../config.md)). Most automatic checks end with nothing to do and cost one tool call.

The exact rules and limits are in [Scheduling](../scheduling.md).
