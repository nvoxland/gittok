"""Evidence attached to a packet's leads, so a writer can write without tool calls.

Everything here is read-only and goes through `gitq`. A lead is the `asdict` of a
`brief.Lead`. Bad coordinates give "" (the writer can still research), never an error.
"""

from __future__ import annotations

from collections import Counter

from codescroll import gitq, research
from codescroll.brief import _useful

LEAD_CAP = 4 * 1024  # bytes of materials per lead
# bytes of materials per packet: get_packet must stay small enough for the harness to show it
# inline (a ~50 KB reply was saved to a file the writer could not read).
PACKET_CAP = 12 * 1024
LEADS_PER_TYPE = 2  # materials for the top leads of each story type; a writer uses 1 or 2
STAT_FILES = 15
DIFF_LINES = 80
WINDOW_LINES = 60
MARKER = "[truncated]"
NOTE = "Materials attached for the leads below. Research only what is missing."


def _cap(text: str, limit: int) -> str:
    raw = text.encode()
    if len(raw) <= limit:
        return text
    return raw[:limit].decode(errors="ignore").rstrip() + f"\n{MARKER}"


def _commit_materials(cfg, root, lead: dict) -> str:
    sha = gitq.rev_parse(root, lead["commit"])
    cap = cfg.settings.research.max_output_bytes
    head = gitq.run(root, "show", "-s", "--date=short", "--format=%an%x1f%ad%x1f%s", sha)
    author, date, subject = head.rstrip("\n").split("\x1f", 2)
    stat = gitq.split_lines(
        gitq.run(root, "show", "--format=", "--stat", "--stat-width=100", sha, max_bytes=cap)
    )
    files, summary = stat[:-1], stat[-1:]
    shown = files[:STAT_FILES] + (
        [f" … {len(files) - STAT_FILES} more files"] if len(files) > STAT_FILES else []
    )
    out = [
        f"commit {sha[:10]} by {author} on {date}: {subject}",
        "",
        "```",
        *shown,
        *summary,
        "```",
    ]
    numstat = gitq.run(root, "show", "--format=", "--numstat", sha, max_bytes=cap)
    changed: dict[str, int] = {}
    for row in gitq.split_lines(numstat):
        add, _, rest = row.partition("\t")
        dele, _, path = rest.partition("\t")
        if add.isdigit() and dele.isdigit() and "=>" not in path and _useful(path):
            changed[path] = int(add) + int(dele)
    if changed:
        want = lead.get("path")
        top = want if want in changed else max(changed, key=lambda p: (changed[p], p))
        diff = gitq.split_lines(
            gitq.run(
                root,
                "show",
                "--format=",
                "--no-color",
                "--no-ext-diff",
                sha,
                "--",
                top,
                max_bytes=cap,
            )
        )
        more = len(diff) - DIFF_LINES
        out += ["", f"diff of {top}:", "```diff", *diff[:DIFF_LINES], "```"]
        if more > 0:
            out.append(f"{MARKER} diff: {more} more lines")
    return "\n".join(out)


def _path_materials(cfg, root, ref: str, lead: dict) -> str:
    path = lead["path"]
    if gitq.object_type(root, ref, path) != "blob":
        return ""
    data = gitq.show_file(root, ref, path)
    if b"\0" in data[:8192]:
        return ""
    blob = gitq.run(root, "rev-parse", f"{ref}:{path}").strip()
    lines = gitq.split_lines(data.decode(errors="replace"))
    total = len(lines)
    span = lead.get("lines")
    start = 1
    if span:
        mid = (span[0] + span[1]) // 2
        start = max(1, min(mid - WINDOW_LINES // 2, total - WINDOW_LINES + 1))
    end = min(total, start + WINDOW_LINES - 1)
    numbered = [f"{i}\t{ln}" for i, ln in enumerate(lines[start - 1 : end], start)]
    out = [
        f"{path} at {ref}: blob {blob[:10]}, {total} lines; lines {start}-{end}:",
        "```",
        *numbered,
        "```",
    ]
    if end < total:
        out.append(f"… {total - end} more lines after {end}")
    if end >= start:
        rows = gitq.blame_range(root, ref, path, start, end)
        shares = Counter(r["author"] for r in rows).most_common(3)
        out.append(
            "blame for those lines: "
            + ", ".join(f"{a} {round(100 * n / len(rows))}%" for a, n in shares)
        )
    dates = gitq.split_lines(gitq.run(root, "log", "--date=short", "--format=%ad", ref, "--", path))
    if dates:
        out.append(f"first commit touching it: {dates[-1]}; last: {dates[0]}")
    return "\n".join(out)


def materials_for(cfg, lead: dict, cache: dict | None = None) -> str:
    """Markdown evidence for one lead (a `Lead` as a dict); "" when there is none."""
    kind = lead.get("kind")
    if kind not in ("commit", "path"):
        return ""
    span = lead.get("lines")
    key = (lead.get("repo"), kind, lead.get("commit"), lead.get("path"), tuple(span or ()))
    if cache is not None and key in cache:
        return cache[key]
    try:
        root, ref = research._resolve(cfg, lead["repo"], None)
        if kind == "commit":
            text = _commit_materials(cfg, root, lead)
        else:
            text = _path_materials(cfg, root, ref, lead)
    except (research.ResearchError, gitq.GitError, KeyError, TypeError, ValueError, OSError):
        text = ""
    text = _cap(text, LEAD_CAP)
    if cache is not None:
        cache[key] = text
    return text


def packet_materials(cfg, refs: list[dict]) -> str:
    """Materials for the top LEADS_PER_TYPE leads of each story type, at most PACKET_CAP bytes."""
    cache: dict = {}
    parts: list[str] = []
    used = 0
    per_type: dict[str, int] = {}
    for lead in refs:
        if per_type.get(lead["story_type"], 0) >= LEADS_PER_TYPE:
            continue
        per_type[lead["story_type"]] = per_type.get(lead["story_type"], 0) + 1
        body = materials_for(cfg, lead, cache)
        if not body:
            continue
        part = f"### [{lead['story_type']}] {lead['text'][:100]}\n\n{body}"
        room = PACKET_CAP - used
        if len(part.encode()) > room:
            parts.append(_cap(part, max(room, 0)) if room > 200 else MARKER)
            break
        parts.append(part)
        used += len(part.encode()) + 2
    if not parts:
        return ""
    return NOTE + "\n\n" + "\n\n".join(parts)
