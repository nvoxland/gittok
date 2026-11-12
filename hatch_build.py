"""Hatch build hook: refuse to build a wheel without the web build.

The wheel bundles `web/build` as `blamescroll/_bundled/web`. Without it an installed app
would serve only a placeholder page, so fail loudly instead.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebBuildCheck(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        if self.target_name != "wheel":
            return
        index = Path(self.root) / "web" / "build" / "index.html"
        if not index.is_file():
            raise RuntimeError(
                f"{index} is missing. Run `npm --prefix web install` and "
                "`npm --prefix web run build` first, then build the wheel again."
            )
