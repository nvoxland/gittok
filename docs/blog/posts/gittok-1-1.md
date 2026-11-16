---
date: 2026-11-13
authors:
  - nvoxland
categories:
  - Releases
---

# GitTok 1.1: your own writing guidance, and a feed that learns better

GitTok 1.1 lets you tell the card writers how you want your posts, makes pairing a phone one simple step, and fixes a set of ways the feed could learn the wrong thing from what you do.

<!-- more -->

```bash
uv tool upgrade gittok
```

Then say "update this GitTok directory" in a Claude Code session there.

## Your own writing guidance

The mix and the rules decide *how many* posts of each kind get made. Now you can also say *how* to write them. `local/guidance.md` in your GitTok directory is free Markdown for the writers:

```markdown
# How I want my cards

- Keep hooks under 12 words.
- I am new to Clojure: explain its syntax when a card shows Clojure code.
- No pop-culture references. Puns are fine.
```

Every writer reads it from the next run on. Or just ask Claude ("keep hooks short") and it edits the file. See [Steer the feed](../../guide/steering.md#your-writing-guidance).

## Pair with a code, everywhere

There is now one way to pair a phone, and it works the same in the browser and in the app on your home screen:

1. Open the feed address on your phone. Claude gives it at the start of each session, or ask: "what is the feed address?"
2. Tap **Pair with a code**.
3. Tell Claude the code: "pair code X6J2-QG".

The QR code page and the pairing link are gone. No page or link holds the pairing token any more, so there is nothing to leak in a screenshot or a chat. See [Get started: pair your phone](../../getting-started/install.md#pair-your-phone).

## A feed that learns better

A review of the learner found several ways it could learn the wrong lesson. All are fixed:

- **One short look no longer turns a read post into a skip.** Read a post for 20 seconds, come back to it for half a second, and it used to count as skipped. Now a post is a skip only when every look at it was short, and an answer or an opened panel always counts.
- **Watch time is counted once.** A comic or a chat you came back to could count its play time twice.
- **The feed shows what exists, in order.** The learner now decides only what gets made: the mix of each new batch. The feed shows every post you have not seen, oldest first, and a 👍 or 👎 no longer reshuffles the posts ahead. A post you saw does not come back a week later (quiz reviews still do).
- **A 👎 you take back is unlearned**, and the story can be told again.
- **"New to you" means new when you saw it.** The learner could record code as familiar because of the very post that showed it to you.
- **A meme template you disliked no longer goes before one you never saw.**
- **Rebuilding the model keeps what it should.** `gittok relearn` now uses the posts' current features, keeps a reset, and keeps what a removed repo taught.
- **Smaller fixes.** No impression loses its score after a clean-up. Quiz answers use the phone's clock, like the other events. Rejected leads are forgotten after the cooldown. A zero in the decay or prior settings is a config error, not a crash.
- **Faster.** A learning pass reads only what is new.

The model is now trained on cleaner data. The details are in [Learning and ranking](../../learning.md).
