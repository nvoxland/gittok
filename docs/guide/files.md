# Your GitTok directory

All your files are in the GitTok directory that you made with `gittok init`. You can move or copy it. You can make more than one, for example one for work and one for your own projects.

```
~/gittok/
├── gittok.yaml                marks the directory, with the gittok version
├── AGENTS.md                  tells the coding agent what this directory is
├── CLAUDE.md                  points to AGENTS.md
├── .mcp.json                  makes Claude Code start the GitTok server
├── .gitignore                 for data/ and repos/, if you put the directory under git
├── .claude/
│   ├── settings.json          session hooks: the feed address, the feed watch
│   ├── skills/                gittok-generate, gittok-steer, gittok-profile-repo
│   └── agents/                gittok-writer, gittok-scout, gittok-illustrator
├── local/                     your settings
│   ├── repos.yaml             the repo list
│   ├── profiles/<repo>.yaml   one profile per repo
│   ├── mascots.yaml           the mascot of each repo
│   ├── guidance.md            your writing guidance for the card writers
│   └── <file>.yaml            optional: your changes to any default
├── data/                      what GitTok makes
│   ├── gittok.db              cards, what you did, what the feed learned
│   ├── assets/                card images, avatars, mascots
│   ├── memes/                 meme templates and fonts
│   ├── models/                the illustration model (about 6 GB), downloaded by itself
│   ├── runs/                  the brief and submissions of each run
│   ├── logs/
│   └── profile.md             your taste profile in plain words, rewritten daily
└── repos/<name>/              clones of repos you added by URL
```

## Who writes what

- **`gittok init` and `gittok update`** own the top-level files and `.claude/`. An update rewrites them, and keeps a file that you edited as `<name>.bak`.
- **`local/` is yours.** Claude edits it only when you ask (or GitTok's own tools do: the repo list, profiles, mascots). An update never touches it. The [Configuration](../config.md) reference lists every file.
- **`data/` and `repos/`** are GitTok's. Garbage collection keeps them small: old cards you read go, saved and liked cards stay longer.

The shipped defaults, the web app and the skill sources are inside the installed `gittok` package, not in this directory.
