"""Refresh the bundled default meme assets from a pinned memegen revision.

Run with `uv run python scripts/vendor_memes.py`; this developer command needs network.
Runtime rendering never downloads assets. Keep upstream notices and source hashes.
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import httpx

from gittok import memes, overlay

REVISION = "083159c998fedbae1065c9e983d050cb4b335b94"
BASE = f"https://raw.githubusercontent.com/jacebrowning/memegen/{REVISION}"


def main():
    root = memes.BUNDLED
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        def get(path):
            response = client.get(f"{BASE}/{path}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content

        def template(name):
            config = get(f"templates/{name}/config.yml")
            if not config or not memes._layout_ok(config):
                raise ValueError(f"Invalid template: {name}")
            files = {f"templates/{name}/config.yml": config}
            for ext in memes.IMAGE_EXTS:
                path = f"templates/{name}/default.{ext}"
                image = get(path)
                if image:
                    files[path] = image
                    return files
            raise ValueError(f"No image: {name}")

        names = overlay.shipped("meme_templates")["templates"]
        files = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for result in pool.map(template, names):
                files.update(result)
        for path in ["LICENSE.txt", "fonts/OFL.txt", "fonts/SIL Open Font License.txt",
                     *(f"fonts/{name}" for name in memes.FONT_FILES.values())]:
            content = get(path)
            if content is None:
                raise ValueError(f"Missing upstream file: {path}")
            files[path] = content
        notices = {}
        for family in ("titilliumweb", "kalam", "notosans"):
            url = f"https://raw.githubusercontent.com/google/fonts/main/ofl/{family}/OFL.txt"
            response = client.get(url)
            response.raise_for_status()
            path = f"fonts/{family}-OFL.txt"
            files[path] = response.content
            notices[path] = url
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {
        "repository": "https://github.com/jacebrowning/memegen",
        "revision": REVISION,
        "font_license_sources": notices,
        "sha256": {name: hashlib.sha256(content).hexdigest()
                   for name, content in sorted(files.items())},
    }
    (root / "SOURCES.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Bundled {len(names)} templates and {len(memes.FONT_FILES)} fonts "
          f"({sum(map(len, files.values())) / 1024 / 1024:.1f} MiB).")


if __name__ == "__main__":
    main()
