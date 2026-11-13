# Your first feed

Start Claude Code in your GitTok directory (`cd ~/gittok`, then `claude`). You manage GitTok by asking Claude in plain words. Claude Code asks for your permission before it runs a GitTok tool.

## 1. Add a repo

Give Claude a directory or a git URL:

> Add the repo at ~/src/myapp to GitTok.

> Add https://example.com/org/storefront.git to GitTok.

GitTok reads a directory in place and never changes it. It clones a URL into `repos/` of the GitTok directory, and fetches it before each analysis.

Then Claude does two things without asking:

1. **It profiles the repo.** It reads the repo and writes the rules that find the code worth teaching. This takes a few minutes and some of your model quota. Claude may ask your permission to run a code analyzer, and it may offer to download grammars.
2. **It makes the first posts.** A run of writers each take a small packet of leads, research them in your repo, and submit posts. GitTok checks each post against git before it stores it.

If the image renderer works, Claude also gives the repo a **mascot**: a small character that the illustration and comic posts draw. It tells you which one it picked. Say "make the mascot a fox" to change it.

## 2. Pair your phone

GitTok is made for your phone. Your phone must be on the same network as your computer, and each device pairs once.

1. **Open the feed address on your phone.** At the start of each Claude Code session, Claude tells you where the feed is, for example *"The feed is at http://192.168.1.57:7313 on your phone"*. If you missed it, ask: "What is the feed address?"
2. **Tap Pair with a code.** A phone that is not paired yet gets this page instead of the feed. It shows a short code, such as `X6J2-QG`.
3. **Tell Claude the code:** "pair code X6J2-QG". A code lasts 10 minutes and works once.

A few seconds later, the feed opens on the phone. That's all: there is no other step to start pairing.

!!! tip "Add it to the home screen"
    In Safari, tap **Share**, then **Add to Home Screen**. The app opens full screen. It keeps its own storage, apart from the browser, so pair it once more inside the app: tap **Pair with a code** and tell Claude the new code.

The feed goes over plain HTTP on your network. Read [Privacy and your network](../guide/privacy.md) before you use it on a shared network. To turn phone access off, say "turn off phone access".

## 3. Scroll your Feed

- **Swipe up** for the next post.
- **Swipe sideways** to go deeper: the explanation, the real code, the real diff.
- **👍** when you liked a post, **👎** for "show less like this". The thumbs shape the posts that get made next.
- **Save** a post to find it again.
- Answer a **quiz**. A wrong answer comes back later.
- Read the **comments**: the cast argues about every post.

The feed is served while the Claude Code session is open. New posts come by themselves while it stays open ([Keep the feed full](../guide/keeping-full.md)).

## What next

- [Steer the feed](../guide/steering.md): "less memes", "more of the sync engine this week".
- [How the feed learns](../guide/learning.md) from what you do.
- [Add more repos](../guide/repos.md), and put them in groups.
