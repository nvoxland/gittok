# Steer the feed

The feed [learns](learning.md) what you like by itself. You can also tell it, in three ways.

| You want to change | Use | Example |
|---|---|---|
| How much of something you get, for a while or for good | A **rule** | "less memes", "focus on billing this week" |
| How the cards are written | Your **writing guidance** | "keep hooks short", "no pop-culture jokes" |
| The starting mix, before the feed learns | The **default mix** | "start with more quizzes" |

## Rules

Say what you want:

> Less memes.

> No more roast cards.

> More of the sync engine this week.

> Focus on the work group.

Your agent turns it into a rule and tells you what it did, for example: *"Added rule 5: memes are limited to 10% of the feed. Say 'undo rule 5' to remove it."*

A rule can **limit** a share (to zero for "never"), **boost** or **prefer** something, or **focus** on it. It can name a format, a story type, a tone, a repo, a group, a directory, or the kind of knowledge a card gives (what, how, why, who, risk). Rules change which cards get made from the next batch on. They do not change the cards already in your feed.

For anything a rule cannot say, such as "no history cards", "leave the legacy folder alone" or "no puns", use your [writing guidance](#your-writing-guidance).

> What rules do I have?

> Undo rule 5.

## Your writing guidance

For what a rule cannot say, write it down. `local/guidance.md` in your GitTok directory is free text for the agents that write the cards. Ask your agent and it edits the file:

> Keep hooks under 12 words.

> I'm new to Clojure, explain its syntax when a card shows Clojure code.

Or write it yourself:

```markdown
# How I want my cards

- Keep hooks under 12 words.
- I am new to Clojure: explain its syntax when a card shows Clojure code.
- No pop-culture references. Puns are fine.
- More about why the code is the way it is, less about who wrote it.
```

Every writer reads it, from the next cards on. GitTok's own rules still win where the two conflict: facts must be true and sourced, and the length limits stay. Keep it under 6000 characters.

## Your own meme templates

GitTok comes with 99 meme templates. To add another one, name a template of [memegen](https://github.com/jacebrowning/memegen):

> Add the "aag" meme template (the Ancient Aliens guy).

> Drop the drake template.

Your agent adds it to `local/meme_templates.yaml` and downloads its image. Only the template image is downloaded; no card text leaves your computer.

## The default mix

The feed starts from a mix of categories and tones, and moves away from it as it learns. To start from another mix:

> Change the default mix: more interactive cards, fewer memes.

Your agent writes the change to `local/defaults.yaml`. Most of the time a rule is the better choice: it says what you want now, and you can undo it.

## Ask what it learned

> What have you learned about me?

> Why am I seeing so many tier lists?

Your agent answers from what the feed learned. To start over:

> Reset my feed.

> Forget what you learned about tones.

A reset clears what the feed learned (all of it, or one part). Your rules stay.

[Configuration](../config.md) lists every file and setting that you can change.
