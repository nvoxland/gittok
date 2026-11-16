# Privacy and your network

GitTok runs on your own machine. It reads the git history of the repos you add, and it serves a feed on a local port.

## What stays private

- **Your repos are read-only.** GitTok never writes to a working tree, an index or a branch of a repo you added by path.
- **No model API of its own.** Your coding agent writes the cards, under your agent's own terms. GitTok draws memes and images on your machine.
- **A repo cannot start a program.** Git runs with hooks, external diff programs and similar features turned off.
- **Secrets are masked.** Text from your repos passes a secret detector before an agent or a card sees it.
- **Text in a repo is data.** The agents are told never to follow instructions found in code, commits or comments, and the writers get no tools that change your settings.

## Phone access

GitTok is made for a phone, so while a session is open the feed server serves the feed to your local network. Know what that means:

- The feed goes over **plain HTTP**, not HTTPS.
- Any device on the same network can reach the port, but it gets nothing until it pairs: you tap **Pair with a code** on it and tell your agent the code that it shows. A code lasts 10 minutes and works once, and only you can approve it, in your agent session.
- Someone who can watch traffic on that network could read the pairing cookie and the cards. Cards hold excerpts of your code.
- So use it on a network you trust, such as your home network. Take care on shared or public Wi-Fi.

To turn it off, say:

> Turn off phone access.

The server then answers this computer only. Say "turn phone access back on" to undo it.

[Advanced setup](../install.md#https-on-a-lan-optional-for-pwa-install) has an optional HTTPS recipe. The full list of what GitTok protects, and what it does not, is in [SECURITY.md](https://github.com/nvoxland/gittok/blob/main/SECURITY.md).
