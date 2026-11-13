# Repos

GitTok makes posts about the repos you add. You can add as many as you like, and group them.

## Add a repo

> Add the repo at ~/src/myapp to GitTok.

> Add https://example.com/org/storefront.git to GitTok.

- **A directory** is read in place. GitTok never writes to it: no checkout, no commit, no change to its config.
- **A URL** is cloned into `repos/<name>/` of your GitTok directory. GitTok owns that clone, and fetches it before each analysis so the posts stay current.

Claude Code asks your permission before it adds a repo. That prompt is your consent.

## Profiles

Right after you add a repo, Claude **profiles** it: it reads the stack, the main directories and a few key files, and writes rules that find the code worth teaching. The rules are data, in `local/profiles/<repo>.yaml`, and GitTok runs and scores them itself. A rule that leads to posts you skip loses weight.

Claude profiles a new repo without asking. For a repo that has a profile, it only **offers** a new one: when the repo's manifests changed, or when several rules do badly. Say "profile myapp" to ask for one.

## Mascots

When the image renderer is installed, each repo gets a mascot: a small character that its illustration and comic posts draw. Claude picks one that fits the repo when you add it.

> Give myapp an owl mascot.

A repo with no mascot gets no mascot or comic posts. All other posts work.

## Groups

> Put myapp and storefront in the work group.

Groups let you steer several repos at once ("focus on the work group this week").

## Remove a repo

> Remove myapp from GitTok.

This removes the posts made from the repo, with their images, its analysis, its profile, the rules on it and its mascot. A clone that GitTok made is deleted. A directory of your own is never touched. What the feed learned about your taste stays.

To keep the posts and the profile, say "remove myapp but keep its data".
