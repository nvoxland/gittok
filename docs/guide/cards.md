# Cards

The docs and the tools call a post a **card**. Every card is about your own code: a commit, a file, a function, a directory, or how they connect.

## Anatomy of a card

- **The hook**: one line that makes you stop scrolling.
- **The visual**: code, a meme, a comic, a chart, a diagram, a group chat, a tier list, and more.
- **Depth panels**: swipe sideways for the explanation, the real code, the diff and the sources.
- **Comments**: the cast argues about the card underneath.

## Kinds of cards

| Kind | Examples |
|---|---|
| Git drama | The commit that got reverted twice. Breaking news about a refactor. A hot take on a module. |
| Explainers | What this function does, explained like you are five. A diagram of how a request flows. |
| Code | A code card with callouts. Red and green flags. A glow-up: before and after. |
| Memes and fun | Memes, text memes, tier lists, dating profiles, horoscopes, a day in the life of a file. |
| Illustrated | A comic or a scene with the repo's mascot. |
| Interactive | Spot the bug. Guess who wrote it. Guess when. This or that. |
| Cross-repo and recent | What changed this week, and stories that span two repos. |

The full list, with the exact visuals, is in [Card formats](../formats.md).

## The cast

Each card has comments from a fixed cast:

| Handle | Voice |
|---|---|
| Greybeard | Grumpy senior engineer who has seen it all. Dry. |
| Penny | Enthusiastic junior. Asks naive-but-good questions. |
| The Archivist | Codebase historian. Loves lore and dates. |
| Meme Compiler | Pure memes, chaotic. |
| Paranoid Sec | Worries about security and failure modes. |
| Ship-It Sam | Hype. Celebrates merges and speed. |

> Make Greybeard sound more tired.

Claude changes a voice for you (`local/personas.yaml`).

## Checked against git

The agent that writes a card must cite its sources. Before GitTok stores a card, it checks every cited commit, file, line range, name and number against git. A card that cites something that does not exist is rejected, and the writer must fix it. A secret in the card text is masked or rejected.

!!! warning "Still check what matters"
    GitTok checks the citations, but it cannot check every sentence that a model writes. Check a claim against the cited commit before you rely on it.

## Quizzes that come back

A quiz you got wrong comes back a day later, then after three days, then a week, until you get it right.
