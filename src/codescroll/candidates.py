"""Candidate miners: find places in the code worth a card, with no LLM (SPEC 10.2).

`mine` reads the files at a ref (one `git ls-tree -r -l`, then batched blob reads through
gitq) and returns candidates: {path, start, end, tag, why, score}. `refresh` stores them;
`load_candidates` reads them back. Patterns per language live in config/languages.yaml.

Tags: entry_point, core, god_file, public_api (structure); long_function, deep_nesting,
many_params, many_branches, long_line, big_literal (shape); smell, commented_out,
skipped_test, catch_all, sleep, magic_number (smell); clever (regex, bit operations,
recursion, macros); stable_core, well_tested (quality).
"""

from __future__ import annotations

import hashlib
import math
import posixpath
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from . import config, db, detectors, gitq
from .config import AnalysisSettings
from .profiles import FileSet, Profile, fileset_for

WINDOW = 40
SMELL = re.compile(
    r"\b(HACK|XXX|FIXME|KLUDGE)\b|\b(work-?around)\b|\b(temporar(?:y|ily))\b"
    r"|\b(do(?:n'?t| not)\s+(?:remove|delete|touch|change))\b",
    re.I,
)
STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
NUMBER = re.compile(r"(?<![\w.#$/-])(?:\d{3,}|\d+\.\d+)(?![\w.])")
YEAR = re.compile(r"(?:19|20)\d\d")
OK_NUMBERS = {"100", "1000", "1024", "0.0", "1.0", "0.5", "100.0"}
CONST_LINE = re.compile(r"^\s*(?:export\s+)?(?:const\s+)?[A-Z][A-Z0-9_]*\s*[:=]")
BIG_LITERAL_INDENT = re.compile(
    r"^\s*(?:[\w.]+\s*(?::[^=]+)?=|(?:export\s+)?(?:const|let|var)\s+\w+[^=]*=|return)"
    r"\s*[\{\[]\s*$"
)
BIG_LITERAL_PARENS = re.compile(r"^\s*\((?:def|defonce)\s")
CLOSERS = ("}", ")", "]")


@dataclass
class Lang:
    name: str
    raw: dict
    th: dict
    func_start: re.Pattern | None
    entry: list[re.Pattern]
    entry_paths: list[re.Pattern]
    imports: list[re.Pattern]
    public: re.Pattern | None
    branch: re.Pattern | None
    skipped: list[re.Pattern]
    catch_all: list[re.Pattern]
    sleep: re.Pattern | None
    regex_lit: re.Pattern | None
    bit_ops: re.Pattern | None
    meta: list[re.Pattern]
    commented_code: re.Pattern | None

    @property
    def comment(self) -> str:
        return self.raw.get("comment", "#")

    @property
    def parens(self) -> bool:
        return self.raw.get("block") == "parens"


@dataclass
class SourceFile:
    path: str
    lang: Lang
    lines: list[str]
    is_test: bool
    meta: dict = field(default_factory=dict)


def _re(pat: str | None) -> re.Pattern | None:
    return re.compile(pat) if pat else None


def _res(pats) -> list[re.Pattern]:
    return [re.compile(p) for p in pats or ()]


def _compile(name: str, raw: dict, base: dict) -> Lang:
    th = {**base, **(raw.get("thresholds") or {})}
    return Lang(
        name=name,
        raw=raw,
        th=th,
        func_start=_re(raw.get("func_start")),
        entry=_res(raw.get("entry_points")),
        entry_paths=_res(raw.get("entry_paths")),
        imports=_res(raw.get("imports")),
        public=_re(raw.get("public")),
        branch=_re(raw.get("branch")),
        skipped=_res(raw.get("skipped_test")),
        catch_all=_res(raw.get("catch_all")),
        sleep=_re(raw.get("sleep")),
        regex_lit=_re(raw.get("regex_literal")),
        bit_ops=_re(raw.get("bit_ops")),
        meta=_res(raw.get("meta")),
        commented_code=_re(raw.get("commented_code")),
    )


@cache
def _default_languages() -> dict:
    try:
        return config.load_languages()
    except config.ConfigError:
        return config.load_languages(Path(__file__).parents[2])


def compiled_languages() -> dict[str, Lang]:
    """The configured languages as compiled `Lang` objects (cached)."""
    return _compiled_languages()


@cache
def _compiled_languages() -> dict[str, Lang]:
    spec = _default_languages()
    base = spec.get("thresholds") or {}
    return {n: _compile(n, raw, base) for n, raw in (spec.get("languages") or {}).items()}


def text_lang(base: dict | None = None) -> Lang:
    """The language of a scanned file with no known extension: no built-in patterns, so only
    profile detectors apply to it."""
    if base is None:
        base = _default_languages().get("thresholds") or {}
    return _compile("text", {"extensions": []}, base)


# ---------- small helpers ----------


def _clip(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _around(line: int, total: int) -> tuple[int, int]:
    """A window of at most WINDOW lines centred on 1-based `line`."""
    start = max(1, line - WINDOW // 2)
    end = min(total, start + WINDOW - 1)
    return max(1, end - WINDOW + 1), end


def _span(a: int, b: int) -> tuple[int, int]:
    return a, min(b, a + WINDOW - 1)


def _cand(path, span, tag, why, score=1.0) -> dict:
    return {"path": path, "start": span[0], "end": span[1], "tag": tag, "why": why, "score": score}


def _is_comment(sf: SourceFile, line: str) -> bool:
    s = line.strip()
    if s.startswith(sf.lang.comment):
        return True
    return sf.lang.comment == "//" and s.startswith(("*", "/*"))


def _in_comment(sf: SourceFile, line: str, idx: int) -> bool:
    pos = line.find(sf.lang.comment)
    return (0 <= pos < idx) or _is_comment(sf, line)


def _first_group(m: re.Match) -> str | None:
    return next((g for g in m.groups() if g), None)


# ---------- reading files ----------


def _read_files(
    path,
    ref,
    settings: AnalysisSettings,
    langs: dict[str, Lang],
    files: FileSet | None = None,
) -> list[SourceFile]:
    """Files at `ref` that the file set reads (scan minus ignore). Generated, vendored and
    fixture files and files with a generated header are left out. A file with no known
    language gets the `text` language. `files` defaults to the bootstrap file set."""
    fs = files or fileset_for(None)
    by_ext = {ext: lang for lang in langs.values() for ext in lang.raw["extensions"]}
    plain = text_lang(next(iter(langs.values())).th if langs else {})
    picked = []
    for p, sha, size in gitq.ls_tree_files(path, ref):
        if not 0 < size <= settings.candidate_max_file_bytes or not fs.reads(p) or not fs.mined(p):
            continue
        picked.append((p, sha, by_ext.get(posixpath.splitext(p)[1]) or plain))
    picked.sort(key=lambda t: t[0])
    picked = picked[: settings.candidate_max_files]
    blobs = gitq.read_blobs(path, list({sha for _, sha, _ in picked}))
    out = []
    for p, sha, lang in picked:
        data = blobs.get(sha)
        if data is None or b"\0" in data[:8000]:
            continue
        lines = data.decode("utf-8", errors="replace").splitlines()
        if fs.has_generated_marker(lines) or any(len(ln) > 2000 for ln in lines):
            continue
        out.append(SourceFile(p, lang, lines, fs.is_test(p)))
    return out


# ---------- imports: fan-in and fan-out ----------


def _norm(s: str) -> str:
    return s.replace("-", "_")


class _Index:
    """Maps import specs to files of the same language."""

    def __init__(self, files: list[SourceFile]):
        self.full: dict[tuple[str, str], str] = {}
        self.suffix: dict[tuple[str, str], set[str]] = {}
        for sf in files:
            if sf.is_test:
                continue
            stem = _norm(posixpath.splitext(sf.path)[0])
            parts = stem.split("/")
            variants = [parts]
            if parts[-1] in ("__init__", "index") and len(parts) > 1:
                variants.append(parts[:-1])
            for v in variants:
                self.full.setdefault((sf.lang.name, "/".join(v)), sf.path)
                for i in range(len(v)):
                    self.suffix.setdefault((sf.lang.name, "/".join(v[i:])), set()).add(sf.path)

    def lookup(self, lang: str, key: str, exact: bool) -> str | None:
        key = _norm(key.strip("/"))
        hit = self.full.get((lang, key))
        if hit or exact:
            return hit
        found = self.suffix.get((lang, key), set())
        return next(iter(found)) if len(found) == 1 else None


def _specs(sf: SourceFile) -> list[tuple[str, list[str]]]:
    """(module spec, imported names) for every import line."""
    out = []
    for line in sf.lines:
        if _is_comment(sf, line):
            continue
        for rx in sf.lang.imports:
            for m in rx.finditer(line):
                names = []
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    names = [n.strip() for n in m.group(2).split(",") if n.strip()]
                out.append((m.group(1), names))
    return out


def _resolve(sf: SourceFile, spec: str, names: list[str], idx: _Index) -> set[str]:
    """Files an import line points at. `from pkg import a, b` can name several modules."""
    lang = sf.lang.name
    here = posixpath.dirname(sf.path)
    style = sf.lang.raw.get("import_style", "dotted")
    named: list[tuple[str, bool]] = []  # (key, exact)
    whole: list[tuple[str, bool]] = []
    if style == "path":
        spec = re.sub(r"\.(?:[cm]?[jt]sx?|svelte)$", "", spec)
        if spec.startswith("."):
            whole.append((posixpath.normpath(posixpath.join(here, spec)), True))
        else:
            alias = re.match(r"(?:\$lib|@|~|src)/(.+)", spec)
            if alias:
                whole.append((alias.group(1), False))
    else:
        dots = len(spec) - len(spec.lstrip("."))
        rest = spec.lstrip(".").replace(".", "/")
        exact = bool(dots)
        if dots:
            base = here
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            rest = posixpath.join(base, rest) if rest else base
        named = [(posixpath.join(rest, n), exact) for n in names]
        whole.append((rest, exact))
    found = {idx.lookup(lang, k, e) for k, e in named}
    found.discard(None)
    if not found:
        found = {idx.lookup(lang, k, e) for k, e in whole}
        found.discard(None)
    found.discard(sf.path)
    return found


def _fan(files: list[SourceFile]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(fan_in: target -> importers, fan_out: importer -> targets), tests excluded."""
    idx = _Index(files)
    fan_in: dict[str, set[str]] = {}
    fan_out: dict[str, set[str]] = {}
    for sf in files:
        if sf.is_test:
            continue
        for spec, names in _specs(sf):
            for target in _resolve(sf, spec, names, idx):
                fan_in.setdefault(target, set()).add(sf.path)
                fan_out.setdefault(sf.path, set()).add(target)
    return fan_in, fan_out


# ---------- structure ----------


def _structure(files, fan_in, fan_out) -> list[dict]:
    out = []
    by_path = {sf.path: sf for sf in files}
    for sf in files:
        if sf.is_test:
            continue
        total = len(sf.lines)
        hits = [
            (i + 1, ln)
            for i, ln in enumerate(sf.lines)
            if not _is_comment(sf, ln) and any(rx.search(ln) for rx in sf.lang.entry)
        ]
        if hits:
            n, ln = hits[0]
            why = f"entry point at line {n}: '{_clip(ln.strip())}'"
            if len(hits) > 1:
                why += f" ({len(hits)} in this file)"
            out.append(_cand(sf.path, _around(n, total), "entry_point", why, len(hits)))
        else:
            for rx in sf.lang.entry_paths:
                if rx.search(sf.path):
                    why = f"entry point by path ({rx.pattern})"
                    out.append(_cand(sf.path, _span(1, total), "entry_point", why, 0.5))
                    break
        if sf.lang.public:
            names = []
            for ln in sf.lines:
                m = sf.lang.public.match(ln)
                if m:
                    names.append(m.group(1))
            if names:
                score = len(names) + 2 * len(fan_in.get(sf.path, ()))
                why = f"{len(names)} public definitions: {', '.join(names[:5])}"
                out.append(_cand(sf.path, _span(1, total), "public_api", why, score))
    for target, importers in fan_in.items():
        sf = by_path[target]
        if sf.is_test or len(importers) < sf.lang.th["min_fan_in"]:
            continue
        eg = ", ".join(sorted(importers)[:3])
        why = f"imported by {len(importers)} files (e.g. {eg})"
        out.append(_cand(target, _span(1, len(sf.lines)), "core", why, len(importers)))
    for importer, targets in fan_out.items():
        sf = by_path[importer]
        if len(targets) >= sf.lang.th["god_fan_out"]:
            why = f"imports {len(targets)} other files of this repo, and has {len(sf.lines)} lines"
            out.append(_cand(importer, _span(1, len(sf.lines)), "god_file", why, len(targets)))
    return out


# ---------- shape: functions ----------


def _scan_parens(lines: list[str], i: int, limit: int = 3000):
    """From line i, walk until brackets balance. Returns (end index, max depth, line of max)."""
    depth = best = 0
    best_at = i
    in_str = False
    started = False
    for j in range(i, min(len(lines), i + limit)):
        k, ln = 0, lines[j]
        while k < len(ln):
            c = ln[k]
            if in_str:
                if c == "\\":
                    k += 1
                elif c == '"':
                    in_str = False
            elif c == "\\":
                k += 1
            elif c == '"':
                in_str = True
            elif c == ";":
                break
            elif c in "([{":
                depth += 1
                started = True
                if depth > best:
                    best, best_at = depth, j
            elif c in ")]}":
                depth -= 1
            k += 1
        if started and depth <= 0:
            return j, best, best_at
    return min(len(lines), i + limit) - 1, best, best_at


def _header_end(lines: list[str], i: int) -> int:
    depth = 0
    for j in range(i, min(len(lines), i + 20)):
        depth += lines[j].count("(") - lines[j].count(")")
        if depth <= 0:
            return j
    return i


def _indent_end(lines: list[str], start: int, hdr: int) -> int:
    ind = _indent(lines[start])
    end = hdr
    for j in range(hdr + 1, len(lines)):
        if not lines[j].strip():
            continue
        if _indent(lines[j]) <= ind:
            if lines[j].lstrip().startswith(CLOSERS):
                end = j
            break
        end = j
    return end


def _count_params(sf: SourceFile, text: str, name: str) -> int:
    text = STRING.sub('""', text)
    at = text.find(name)
    open_c = "[" if sf.lang.parens else "("
    s = text.find(open_c, at if at >= 0 else 0)
    if s < 0:
        return 0
    depth, parts, cur = 0, [], ""
    for c in text[s:]:
        if c in "([{":
            depth += 1
            if depth == 1:
                continue
        if c in ")]}":
            depth -= 1
            if depth == 0:
                break
        if depth == 1 and (c == "," or (sf.lang.parens and c.isspace())):
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    skip = {"", "self", "cls", "*", "/", "**", "&"}
    return sum(1 for p in parts if p.strip().split(":")[0].split("=")[0].strip() not in skip)


def _nesting(lines: list[str], i: int, hdr: int, end: int) -> tuple[int, int]:
    stack = [_indent(lines[i])]
    best, best_at = 0, i
    for j in range(hdr + 1, end + 1):
        ln = lines[j]
        s = ln.strip()
        if not s or s.startswith(CLOSERS) or s.startswith(("#", "//", "*", "/*")):
            continue
        ind = _indent(ln)
        while ind <= stack[-1] and len(stack) > 1:
            stack.pop()
        if ind > stack[-1]:
            stack.append(ind)
        if len(stack) - 1 > best:
            best, best_at = len(stack) - 1, j
    return best, best_at


def _functions(sf: SourceFile) -> list[dict]:
    fs = sf.lang.func_start
    if fs is None:
        return []
    out = []
    for i, line in enumerate(sf.lines):
        m = fs.match(line)
        name = _first_group(m) if m else None
        if not name or _is_comment(sf, line):
            continue
        if sf.lang.parens:
            end, depth, depth_at = _scan_parens(sf.lines, i)
            hdr = i
        else:
            hdr = _header_end(sf.lines, i)
            end = _indent_end(sf.lines, i, hdr)
            depth, depth_at = _nesting(sf.lines, i, hdr, end)
        out.append(
            {"name": name, "start": i, "hdr": hdr, "end": end, "depth": depth, "depth_at": depth_at}
        )
    return out


def _shape(sf: SourceFile) -> list[dict]:
    out = []
    th, lines, total = sf.lang.th, sf.lines, len(sf.lines)
    for f in _functions(sf):
        a, b, name = f["start"], f["end"], f["name"]
        length = b - a + 1
        if length >= th["long_function"]:
            why = f"{name}() is {length} lines long, from line {a + 1} to {b + 1}"
            out.append(_cand(sf.path, _span(a + 1, b + 1), "long_function", why, length))
        if f["depth"] >= th["deep_nesting"]:
            at = f["depth_at"] + 1
            why = f"nesting depth {f['depth']} at line {at} in {name}()"
            out.append(_cand(sf.path, _around(at, total), "deep_nesting", why, f["depth"]))
        text = "\n".join(lines[a : min(b + 1, a + 40)])
        n = _count_params(sf, text, name)
        if n >= th["many_params"]:
            why = f"{name}() takes {n} parameters (line {a + 1})"
            out.append(_cand(sf.path, _span(a + 1, b + 1), "many_params", why, n))
        if sf.lang.branch:
            body = lines[a : b + 1] if sf.lang.parens else lines[f["hdr"] + 1 : b + 1]
            nb = sum(len(sf.lang.branch.findall(ln)) for ln in body if not _is_comment(sf, ln))
            if nb >= th["many_branches"]:
                why = f"{name}() has {nb} branches (line {a + 1})"
                out.append(_cand(sf.path, _span(a + 1, b + 1), "many_branches", why, nb))
        if len(name) >= 3:
            q = re.escape(name)
            if sf.lang.parens:
                rx = re.compile(rf"\(\s*{q}[\s)]")
                body_from = a + 1
            else:
                rx = re.compile(rf"(?<![\w.$]){q}\s*\(|\b(?:self|this|cls)\.{q}\s*\(")
                body_from = f["hdr"] + 1
            for j in range(body_from, b + 1):
                if not _is_comment(sf, lines[j]) and rx.search(lines[j]):
                    why = f"recursion: {name}() calls itself at line {j + 1}"
                    out.append(_cand(sf.path, _around(j + 1, total), "clever", why, 1))
                    break
    for i, ln in enumerate(lines):
        if len(ln) > th["long_line"] and "http" not in ln:
            why = f"line {i + 1} is {len(ln)} characters long"
            out.append(_cand(sf.path, _around(i + 1, total), "long_line", why, len(ln)))
    out += _big_literals(sf)
    return out


def _big_literals(sf: SourceFile) -> list[dict]:
    out = []
    lines, th = sf.lines, sf.lang.th
    rx = BIG_LITERAL_PARENS if sf.lang.parens else BIG_LITERAL_INDENT
    skip_to = -1
    for i, ln in enumerate(lines):
        if i <= skip_to or not rx.match(ln):
            continue
        end = _scan_parens(lines, i)[0] if sf.lang.parens else _indent_end(lines, i, i)
        skip_to = end
        n = end - i + 1
        if n >= th["big_literal"]:
            why = f"literal of {n} lines starting at line {i + 1}"
            out.append(_cand(sf.path, _span(i + 1, end + 1), "big_literal", why, n))
    return out


# ---------- smell and clever markers ----------


def _strip_strings(line: str) -> str:
    return STRING.sub('""', line)


def _markers(sf: SourceFile) -> list[dict]:
    out = []
    lines, total, lang, th = sf.lines, len(sf.lines), sf.lang, sf.lang.th
    magic: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        n = i + 1
        s = ln.strip()
        if not s:
            continue
        m = SMELL.search(ln)
        if m and _in_comment(sf, ln, m.start()):
            kw = m.group(0).upper()
            why = f"{kw} comment at line {n}: '{_clip(s.lstrip('#/;* '))}'"
            score = 2 if kw in ("HACK", "XXX") else 1
            out.append(_cand(sf.path, _around(n, total), "smell", why, score))
        if sf.is_test:
            if any(rx.search(ln) for rx in lang.skipped):
                why = f"skipped test at line {n}: '{_clip(s)}'"
                out.append(_cand(sf.path, _around(n, total), "skipped_test", why))
            continue
        if _is_comment(sf, ln):
            continue
        if any(rx.search(ln) for rx in lang.catch_all):
            why = f"catch-all handler at line {n}: '{_clip(s)}'"
            out.append(_cand(sf.path, _around(n, total), "catch_all", why))
        if lang.sleep and lang.sleep.search(ln):
            out.append(
                _cand(sf.path, _around(n, total), "sleep", f"sleep call at line {n}: '{_clip(s)}'")
            )
        bare = _strip_strings(ln)
        if lang.regex_lit:
            m = lang.regex_lit.search(ln)
            if m:
                pat = m.group(m.lastindex or 0)
                why = f"regex literal at line {n}: {_clip(pat, 50)} ({len(pat)} chars)"
                out.append(_cand(sf.path, _around(n, total), "clever", why, len(pat) / 10))
        if lang.bit_ops and lang.bit_ops.search(bare):
            why = f"bit operation at line {n}: '{_clip(s, 50)}'"
            out.append(_cand(sf.path, _around(n, total), "clever", why))
        if any(rx.search(ln) for rx in lang.meta):
            why = f"metaprogramming at line {n}: '{_clip(s, 50)}'"
            out.append(_cand(sf.path, _around(n, total), "clever", why, 2))
        if not CONST_LINE.match(ln) and not s.startswith(("import ", "from ", "(ns ")):
            for num in NUMBER.findall(bare):
                if num not in OK_NUMBERS and not YEAR.fullmatch(num):
                    magic.append((n, num))
                    break
    if len(magic) >= th["magic_numbers"]:
        n, num = magic[0]
        why = f"{len(magic)} magic numbers, first {num} at line {n}"
        out.append(_cand(sf.path, _around(n, total), "magic_number", why, len(magic)))
    out += _commented_out(sf)
    return out


def _commented_out(sf: SourceFile) -> list[dict]:
    lang = sf.lang
    if sf.is_test or lang.commented_code is None:
        return []
    out, run = [], []

    def flush():
        if len(run) >= lang.th["commented_out"]:
            code = sum(1 for _, t in run if lang.commented_code.match(t))
            if code * 10 >= len(run) * 6:
                a, b = run[0][0], run[-1][0]
                why = f"{len(run)} lines of commented-out code at line {a}"
                out.append(_cand(sf.path, _span(a, b), "commented_out", why, len(run)))
        run.clear()

    for i, ln in enumerate(sf.lines):
        s = ln.strip()
        if s.startswith(lang.comment) and not s.startswith(("#!", "#:", "#[")):
            run.append((i + 1, s.lstrip(lang.comment[0] + " ").rstrip()))
        else:
            flush()
    flush()
    return out


# ---------- quality ----------


def _quality(files, fan_in, sig, t0, path, ref) -> list[dict]:
    out = []
    by_path = {sf.path: sf for sf in files}
    popular = {
        p: len(i)
        for p, i in fan_in.items()
        if p in by_path and len(i) >= by_path[p].lang.th["stable_fan_in"]
    }
    if popular:
        days = min(by_path[p].lang.th["stable_days"] for p in popular)
        changed = gitq.paths_changed_since(path, ref, t0 - days * 86400)
        for p, n in popular.items():
            if p not in changed:
                why = f"imported by {n} files and unchanged for {days}+ days"
                out.append(_cand(p, _span(1, len(by_path[p].lines)), "stable_core", why, n))
    for pair in (sig or {}).get("co_change") or ():
        a, b = by_path.get(pair["a"]), by_path.get(pair["b"])
        if not a or not b or a.is_test == b.is_test:
            continue
        src, test = (b, a) if a.is_test else (a, b)
        if pair["jaccard"] >= src.lang.th["tested_jaccard"]:
            why = (
                f"changes with its test {test.path} "
                f"(jaccard {pair['jaccard']:.2f}, {pair['count']} commits)"
            )
            out.append(
                _cand(src.path, _span(1, len(src.lines)), "well_tested", why, pair["jaccard"])
            )
    return out


# ---------- driver and storage ----------


def _bound(cands: list[dict], limit: int, per_file: int = 3) -> list[dict]:
    """Keep the best `limit` per tag (per tag and rule for profile rules), `per_file` per file."""
    groups: dict[tuple, list[dict]] = {}
    for c in cands:
        groups.setdefault((c["tag"], c.get("rule_id")), []).append(c)
    out = []
    for rows in groups.values():
        rows.sort(key=lambda c: (-c["score"], c["path"], c["start"]))
        seen: dict[str, int] = {}
        kept = 0
        for c in rows:
            if kept >= limit:
                break
            if seen.get(c["path"], 0) >= per_file:
                continue
            seen[c["path"]] = seen.get(c["path"], 0) + 1
            out.append(c)
            kept += 1
    return out


# ---------- scoring: one formula for every candidate (docs/learning.md section 12) ----------
#   score = weight x strength x fanin x size x age x churn


def fanin_factor(fan_in: int) -> float:
    """1.0 for a file nobody imports, up to 2.0 for one imported by 15 or more files."""
    return 1 + 0.25 * min(4.0, math.log2(1 + fan_in))


def size_factor(file_lines: int) -> float:
    """Tiny files make thin cards: 0.7 under 10 lines, 0.85 under 20, else 1."""
    return 0.7 if file_lines < 10 else 0.85 if file_lines < 20 else 1.0


def age_factor(changed_recently: bool) -> float:
    """Code touched in the last AGE_DAYS before the analyzed commit counts 1.0, cold code 0.85."""
    return 1.0 if changed_recently else 0.85


def churn_factor(share: float | None) -> float:
    """1 + 0.5 x share, where share is the file's 90-day commit count over the top file's."""
    return 1.0 if share is None else 1 + 0.5 * min(1.0, share)


def strength(raw: float) -> float:
    """The miner's own count (lines, branches, hits) as log2(1 + raw): keeps the order in a tag."""
    return math.log2(1 + max(0.0, raw))


AGE_DAYS = 90


def _rescore(out, files, fan_in, sig, t0, path, ref) -> None:
    lines = {sf.path: len(sf.lines) for sf in files}
    recent = gitq.paths_changed_since(path, ref, t0 - AGE_DAYS * 86400) if out else set()
    top = ((sig or {}).get("churn") or {}).get("files", {}).get(str(AGE_DAYS)) or []
    most = max((r["commits"] for r in top), default=0)
    commits = {r["path"]: r["commits"] for r in top}
    for c in out:
        p = c["path"]
        share = commits.get(p, 0) / most if most else None
        c["score"] = round(
            c.pop("weight", 1.0)
            * strength(c["score"])
            * fanin_factor(len(fan_in.get(p, ())))
            * size_factor(lines.get(p, 0))
            * age_factor(p in recent)
            * churn_factor(share),
            4,
        )


def mine(
    path,
    ref: str,
    t0: int,
    sig: dict | None,
    settings: AnalysisSettings,
    languages=None,
    profile: Profile | None = None,
) -> list[dict]:
    """All candidates at `ref`, bounded per tag. Read-only.

    The profile's file set (scan, ignore, kinds) decides which files are read; with no profile
    the bootstrap file set applies. `profile` also adds its detector hits, and these may land in
    files of the `text` language, which the built-in miners skip."""
    spec = languages or _default_languages()
    base = spec.get("thresholds") or {}
    langs = {n: _compile(n, raw, base) for n, raw in (spec.get("languages") or {}).items()}
    all_files = _read_files(path, ref, settings, langs, fileset_for(profile))
    files = [sf for sf in all_files if sf.lang.name != "text"]
    fan_in, fan_out = _fan(files)
    out = _structure(files, fan_in, fan_out)
    for sf in files:
        if not sf.is_test:
            out += _shape(sf)
        out += _markers(sf)
    out += _quality(files, fan_in, sig, t0, path, ref)
    if profile is not None:
        out += detectors.run(profile, all_files)
    _rescore(out, all_files, fan_in, sig, t0, path, ref)
    # Profile hits keep one row per stored key (path, start, tag); a built-in hit wins a clash.
    taken = {(c["path"], c["start"], c["tag"]) for c in out if not c.get("rule_id")}
    ruled: dict[tuple, dict] = {}
    for c in sorted((c for c in out if c.get("rule_id")), key=lambda c: -c["score"]):
        k = (c["path"], c["start"], c["tag"])
        if k not in taken:
            taken.add(k)
            ruled[k] = c
    out = [c for c in out if not c.get("rule_id")] + list(ruled.values())
    return _bound(out, settings.candidates_per_tag)


def window_hash(lines: list[str]) -> str:
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()


def window_hashes(path, ref: str, items: list[dict]) -> dict[tuple[str, int, int], str]:
    """(path, start, end) -> sha1 of the window text at `ref`. Items have path, start, end."""
    wanted = {i["path"] for i in items}
    if not wanted:
        return {}
    blobs = gitq.ls_tree_blobs(path, ref)
    data = gitq.read_blobs(path, list({blobs[p] for p in wanted if p in blobs}))
    texts: dict[str, list[str]] = {}
    for p in wanted:
        raw = data.get(blobs.get(p, ""))
        if raw is not None:
            texts[p] = raw.decode("utf-8", errors="replace").splitlines()
    return {
        (i["path"], i["start"], i["end"]): window_hash(texts[i["path"]][i["start"] - 1 : i["end"]])
        for i in items
        if i["path"] in texts
    }


def refresh(
    conn,
    repo: str,
    path,
    head: str,
    t0: int,
    sig: dict,
    settings: AnalysisSettings,
    profile: Profile | None = None,
) -> int:
    """Mine `head` and store the result; rows the miners no longer find are removed."""
    found = mine(path, head, t0, sig, settings, profile=profile)
    hashes = window_hashes(path, head, found)
    now = db.now_iso()
    with db.immediate(conn):
        for c in found:
            conn.execute(
                "INSERT INTO candidates(repo, path, line_start, line_end, tag, why, score, "
                "head_sha, first_seen_at, last_seen_at, window_hash, rule_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(repo, path, line_start, tag) DO UPDATE SET "
                "line_end=excluded.line_end, why=excluded.why, score=excluded.score, "
                "head_sha=excluded.head_sha, last_seen_at=excluded.last_seen_at, "
                "window_hash=excluded.window_hash, rule_id=excluded.rule_id",
                (
                    repo,
                    c["path"],
                    c["start"],
                    c["end"],
                    c["tag"],
                    c["why"],
                    c["score"],
                    head,
                    now,
                    now,
                    hashes.get((c["path"], c["start"], c["end"])),
                    c.get("rule_id"),
                ),
            )
        keep = {(c["path"], c["start"], c["tag"]) for c in found}
        for r in conn.execute(
            "SELECT id, path, line_start, tag FROM candidates WHERE repo = ?", (repo,)
        ).fetchall():
            if (r["path"], r["line_start"], r["tag"]) not in keep:
                conn.execute("DELETE FROM candidates WHERE id = ?", (r["id"],))
    return len(found)


def load_candidates(
    conn, repo: str, tag: str | None = None, limit: int | None = None
) -> list[dict]:
    """Stored candidates for `repo`, best score first."""
    sql = (
        "SELECT path, line_start AS start, line_end AS end, tag, why, score, head_sha, "
        "first_seen_at, last_seen_at, rule_id FROM candidates WHERE repo = ?"
    )
    args: list = [repo]
    if tag:
        sql += " AND tag = ?"
        args.append(tag)
    sql += " ORDER BY score DESC, path, line_start"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def load_rated(
    conn,
    repo: str,
    min_teachable: int = 1,
    verdicts: list[str] | None = None,
    tags: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Current candidates joined to their scout rating (same window text), best rated first."""
    sql = (
        "SELECT c.id, c.path, c.line_start AS start, c.line_end AS end, c.tag, c.why AS reason, "
        "c.score, c.head_sha, c.rule_id, r.teachable, r.verdict, r.concept, r.why, r.rated_at "
        "FROM candidates c JOIN candidate_ratings r ON r.repo = c.repo AND r.path = c.path "
        "AND r.line_start = c.line_start AND r.tag = c.tag AND r.window_hash = c.window_hash "
        "WHERE c.repo = ? AND r.teachable >= ?"
    )
    args: list = [repo, min_teachable]
    for col, vals in (("r.verdict", verdicts), ("c.tag", tags)):
        if vals is not None:
            sql += f" AND {col} IN ({','.join('?' * len(vals))})"
            args += list(vals)
    sql += " ORDER BY r.teachable DESC, c.score DESC, c.path, c.line_start"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]
