"""Hatch build hook: put the web build into the wheel, and refuse to build a wheel without it.

The wheel bundles `web/build` as `gittok/_bundled/web`. Without it an installed app
would serve only a placeholder page, so fail loudly instead. An editable (development)
install reads `web/build` from the clone, so it needs neither the check nor the copy.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebBuildCheck(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        if self.target_name != "wheel" or version == "editable":
            return
        build = Path(self.root) / "web" / "build"
        if not (build / "index.html").is_file():
            raise RuntimeError(
                f"{build / 'index.html'} is missing. Run `npm --prefix web install` and "
                "`npm --prefix web run build` first, then build the wheel again."
            )
        build_data["force_include"][str(build)] = "gittok/_bundled/web"
