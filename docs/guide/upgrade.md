# Upgrade and uninstall

## Upgrade

```bash
uv tool upgrade gittok
```

uv remembers the `images` extra if you installed with it.

Then start your agent in your GitTok directory and say:

> Update this GitTok directory.

Or run `gittok update` in the directory. It writes the new skills, agents and settings. It does not touch `local/`, `data/` or `repos/`. If you edited one of its files, it keeps your copy as `<name>.bak`.

What changed in each release is on the [blog](../blog/index.md).

## Uninstall

Delete the GitTok directory, then:

```bash
uv tool uninstall gittok
```

A repo that you added by path is your own directory. GitTok never touches it.
