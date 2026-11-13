# How the feed learns

GitTok has one learner. It decides **what gets made next**: the mix of each new batch of posts. It learns only from what you do in the feed, and it all stays on your machine.

It does not reorder posts that already exist. Posts are made a few at a time as you scroll, so the feed simply shows you every post you have not seen, oldest first. Your 👍 and 👎 change what gets made after that.

## What it watches

For each card you see, it scores how it went:

- **How long you watched.** Like a video: the share of the card you read, or the share of a comic or a chat that played. Time on screen after a card finished counts for nothing.
- **What you did.** Opened the depth panels, tapped a source, answered the quiz, replayed it, scrolled back to it.
- **👍** lifts the score and counts double.
- **👎** ("show less like this") sets the score to zero and counts four times. It does not matter why: already known, boring, not your kind of card. The learner works out what it was from all your 👎 and 👍 over many cards.
- **A skip**: you swiped on in under a second, and did nothing else.

Changed your mind? Take the 👎 back and it is unlearned.

## What it learns about

Each card has features: its repo and directory, the file and its language, the story type, the format, the tone, the persona, the kind of knowledge it gives (what, how, why, who, risk), and how well you knew that code when you saw it.

The learner gives each feature a weight, and learns them together. So when memes get 👎 in many places, "meme" takes the blame, and the places stay neutral.

## How it uses what it learned

- **What gets made.** The weights choose the mix of the next batch (categories, formats, tones, personas, repos, the kind of knowledge) and rank the leads that writers get. Make more of what you like, and a little of everything else, so the feed does not narrow to one kind of post.
- **What you follow.** Follow a file on its page, and more posts about its directory get made.
- **What you know.** GitTok tracks which parts of each repo you have seen. New code gets a push, so the feed keeps teaching.

Old taste fades: what you did a few weeks ago counts less than what you did today.

## You are in charge

- Rules beat the learner: "less memes" applies to the very next batch ([Steer the feed](steering.md)).
- "What have you learned about me?" shows the learned taste.
- "Reset my feed" forgets it, all of it or one part.

The exact formulas are in [Learning and ranking](../learning.md).
