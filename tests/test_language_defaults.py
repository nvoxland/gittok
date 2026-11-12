"""The shipped defaults serve the common languages, not three stacks: each language entry of
config/languages.yaml finds something sensible in a small fixture, with and without the
tree-sitter layer, and the default file set and file type tables know its files."""

from pathlib import Path

import pytest
import yaml

from gittok import candidates, config, gitq, profiles, structure
from gittok.config import AnalysisSettings
from tests.fixture_repo import build_history_repo

ROOT = Path(__file__).parents[1]


def body(line: str, n: int = 56) -> str:
    return "".join(line.format(i=i) + "\n" for i in range(n))


# language -> (source path, source text, test path, test text). Each source has: one long
# function called `process`, an entry point, a catch-all handler, a sleep, a regex literal and
# a HACK comment. Each test file has one skipped test.
FIXTURES = {
    "go": (
        "cmd/server/main.go",
        'package main\n\nimport (\n\t"net/http"\n\t"regexp"\n\t"time"\n)\n\n'
        "var idPattern = regexp.MustCompile(`^[a-z]{3}-[0-9]{4}$`)\n\n"
        'func main() {\n\thttp.HandleFunc("/orders", Process)\n}\n\n'
        "// HACK: remove once the queue is fixed\n"
        "func Process(w http.ResponseWriter, r *http.Request) {\n"
        "\tdefer func() {\n\t\tif err := recover(); err != nil {\n\t\t\treturn\n\t\t}\n\t}()\n"
        "\ttime.Sleep(2 * time.Second)\n" + body("\tx{i} := {i}") + "}\n",
        "pkg/orders/orders_test.go",
        'package orders\n\nimport "testing"\n\nfunc TestOrders(t *testing.T) {\n'
        '\tt.Skip("flaky")\n}\n',
    ),
    "rust": (
        "src/main.rs",
        "use regex::Regex;\nuse std::thread;\n\n"
        "#[tokio::main]\nasync fn main() {\n    process(1);\n}\n\n"
        "// HACK: remove once the queue is fixed\n"
        "pub fn process(n: u32) -> u32 {\n"
        '    let re = Regex::new(r"^[a-z]{3}-[0-9]{4}$").unwrap();\n'
        "    thread::sleep(std::time::Duration::from_secs(2));\n"
        "    let r = std::panic::catch_unwind(|| 1);\n"
        + body("    let x{i} = {i};")
        + "    n\n}\n",
        "tests/orders.rs",
        "#[test]\n#[ignore]\nfn orders_work() {\n    assert!(true);\n}\n",
    ),
    "java": (
        "src/main/java/com/acme/OrderController.java",
        "package com.acme;\n\nimport java.util.regex.Pattern;\n\n"
        "@RestController\npublic class OrderController {\n"
        '    private static final Pattern ID = Pattern.compile("^[a-z]{3}-[0-9]{4}$");\n\n'
        "    // HACK: remove once the queue is fixed\n"
        '    @GetMapping("/orders")\n'
        "    public String process(String id) {\n"
        "        try {\n            Thread.sleep(2000);\n"
        "        } catch (Exception e) {\n            return null;\n        }\n"
        + body("        int x{i} = {i};")
        + "        return id;\n    }\n}\n",
        "src/test/java/com/acme/OrderControllerTest.java",
        "package com.acme;\n\nclass OrderControllerTest {\n    @Disabled\n    @Test\n"
        "    void works() {\n    }\n}\n",
    ),
    "ruby": (
        "app/orders.rb",
        "require 'json'\n\nID = /^[a-z]{3}-[0-9]{4}$/\n\n"
        "get '/orders' do\n  process(1)\nend\n\n"
        "# HACK: remove once the queue is fixed\n"
        "def process(n)\n  begin\n    sleep 2\n  rescue StandardError => e\n    nil\n  end\n"
        + body("  x{i} = {i}")
        + "  n\nend\n",
        "spec/orders_spec.rb",
        "describe 'orders' do\n  xit 'works' do\n    expect(1).to eq(1)\n  end\nend\n",
    ),
    "kotlin": (
        "src/main/kotlin/com/acme/Orders.kt",
        "package com.acme\n\nimport kotlinx.coroutines.delay\n\n"
        'val ID = Regex("^[a-z]{3}-[0-9]{4}$")\n\n'
        "fun main() {\n    process(1)\n}\n\n"
        "// HACK: remove once the queue is fixed\n"
        "fun process(n: Int): Int {\n"
        "    try {\n        Thread.sleep(2000)\n"
        "    } catch (e: Exception) {\n        return 0\n    }\n"
        + body("    val x{i} = {i}")
        + "    return n\n}\n",
        "src/test/kotlin/com/acme/OrdersTest.kt",
        "package com.acme\n\nclass OrdersTest {\n    @Disabled\n    @Test\n"
        "    fun works() {\n    }\n}\n",
    ),
    "csharp": (
        "src/Api/OrdersController.cs",
        "using System.Text.RegularExpressions;\n\nnamespace Acme.Api;\n\n"
        "[ApiController]\npublic class OrdersController\n{\n"
        '    private static readonly Regex Id = new Regex("^[a-z]{3}-[0-9]{4}$");\n\n'
        "    // HACK: remove once the queue is fixed\n"
        '    [HttpGet("/orders")]\n'
        "    public string Process(string id)\n    {\n"
        "        try\n        {\n            Thread.Sleep(2000);\n        }\n"
        "        catch (Exception e)\n        {\n            return null;\n        }\n"
        + body("        var x{i} = {i};")
        + "        return id;\n    }\n}\n",
        "tests/Api.Tests/OrdersControllerTests.cs",
        "namespace Acme.Api.Tests;\n\npublic class OrdersControllerTests\n{\n"
        '    [Fact(Skip = "flaky")]\n    public void Works()\n    {\n    }\n}\n',
    ),
    "php": (
        "routes/web.php",
        "<?php\n\nuse App\\Models\\Order;\n\n"
        "Route::get('/orders', 'process');\n\n"
        "// HACK: remove once the queue is fixed\n"
        "function process($id)\n{\n"
        "    if (!preg_match('/^[a-z]{3}-[0-9]{4}$/', $id)) {\n        return null;\n    }\n"
        "    try {\n        sleep(2);\n"
        "    } catch (\\Exception $e) {\n        return null;\n    }\n"
        + body("    $x{i} = {i};")
        + "    return $id;\n}\n",
        "tests/OrdersTest.php",
        "<?php\n\nclass OrdersTest extends TestCase\n{\n    public function testWorks()\n    {\n"
        "        $this->markTestSkipped('flaky');\n    }\n}\n",
    ),
    "swift": (
        "Sources/App/main.swift",
        "import Foundation\n\n"
        'let idPattern = try! NSRegularExpression(pattern: "^[a-z]{3}-[0-9]{4}$")\n\n'
        "// HACK: remove once the queue is fixed\n"
        "func process(n: Int) -> Int {\n"
        "    do {\n        sleep(2)\n        try risky()\n"
        "    } catch {\n        return 0\n    }\n"
        + body("    let x{i} = {i}")
        + "    return n\n}\n",
        "Tests/AppTests/OrdersTests.swift",
        "import XCTest\n\nfinal class OrdersTests: XCTestCase {\n    func testWorks() throws {\n"
        '        throw XCTSkip("flaky")\n    }\n}\n',
    ),
}
WITH_GRAMMAR = ("go", "rust", "java", "ruby")


def mine(tmp_path, lang):
    src, text, test, test_text = FIXTURES[lang]
    r = build_history_repo(
        tmp_path / "r", [("one", {src: text, test: test_text}, "2026-01-01T10:00:00+00:00")]
    )
    t0 = gitq.commit_time(r.path, "main")
    return candidates.mine(r.path, "main", t0, {}, AnalysisSettings())


def tags(found, path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in found:
        if c["path"] == path:
            out.setdefault(c["tag"], []).append(c["why"])
    return out


def check(found, lang):
    src, _, test, _ = FIXTURES[lang]
    got = tags(found, src)
    name = "Process" if lang in ("go", "csharp") else "process"
    assert any(f"{name}() is" in w for w in got.get("long_function", [])), (lang, got)
    for tag in ("entry_point", "catch_all", "sleep", "smell"):
        assert tag in got, (lang, tag, got)
    assert any("regex literal" in w and "[a-z]{3}" in w for w in got.get("clever", [])), got
    assert "skipped_test" in tags(found, test), (lang, tags(found, test))


@pytest.mark.parametrize("lang", sorted(FIXTURES))
def test_regex_patterns_find_the_shapes_of_each_language(lang, tmp_path, monkeypatch):
    """With no grammar downloaded (a new install), the regex layer alone reads the language."""
    monkeypatch.setattr(structure, "available", lambda: False)
    assert lang in candidates.compiled_languages()
    check(mine(tmp_path, lang), lang)


@pytest.mark.parametrize("lang", WITH_GRAMMAR)
def test_tree_sitter_and_regex_patterns_work_together(lang, tmp_path):
    """A language with a tags query keeps its definitions from tree-sitter; the regex entry
    adds entry points, skipped tests, catch-alls, sleeps and regex literals."""
    if not (structure.available() and structure.ready(lang)):
        pytest.skip("needs the tree-sitter grammar (structure --prefetch)")
    check(mine(tmp_path, lang), lang)


def test_a_language_with_a_query_keeps_its_import_rules_next_to_its_regex_entry():
    langs = candidates.compiled_languages()
    assert langs["go"].raw["import_style"] == "module" and langs["go"].raw["import_unit"] == "dir"
    assert langs["rust"].raw["import_skip_heads"] == ["crate", "self", "super"]
    assert langs["python"].raw["import_style"] == "dotted"  # its own value stays
    assert langs["typescript"].raw["import_style"] == "path"


def test_a_language_with_no_entry_still_gets_the_text_rules(tmp_path):
    """Scala has no entry and no query: comment markers, long lines and deep indentation."""
    text = "object A {\n  // HACK: remove once the queue is fixed\n  val x = 1\n}\n"
    r = build_history_repo(
        tmp_path / "r", [("one", {"src/A.scala": text}, "2026-01-01T10:00:00+00:00")]
    )
    t0 = gitq.commit_time(r.path, "main")
    found = candidates.mine(r.path, "main", t0, {}, AnalysisSettings())
    assert [c["tag"] for c in found] == ["smell"]


# --- the default file set -----------------------------------------------------------------------

READ = [
    "src/a.py", "src/a.clj", "web/a.ts", "web/a.svelte", "cmd/a.go", "src/a.rs", "app/a.rb",
    "src/main/java/A.java", "src/main/kotlin/A.kt", "src/Api/A.cs", "routes/a.php",
    "Sources/App/a.swift", "src/a.c", "include/a.h", "src/a.cpp", "src/A.scala", "lib/a.ex",
    "lib/a.dart", "scripts/a.sh", "src/a.lua", "web/a.vue",
]  # fmt: skip
NOT_READ = [
    "node_modules/x/a.js", "vendor/a.go", "target/classes/A.java", "obj/Debug/A.cs",
    "Pods/X/a.swift", "build/a.kt", ".gradle/a.kt", "coverage/a.js", "_build/dev/a.ex",
    "a.min.js", "web/a.d.ts", "api/a_pb2.py", "api/a.pb.go", "DerivedData/a.swift",
]  # fmt: skip
KINDS = {
    "test": ["src/test/java/ATest.java", "pkg/a_test.go", "spec/a_spec.rb", "tests/a.rs",
             "Tests/AppTests/ATests.swift", "src/ATests.cs", "web/a.test.ts", "tests/ATest.php"],
    "generated": ["api/gen/a.go", "lib/a.g.dart", "src/A.Designer.cs", "src/a.generated.ts",
                  "src/__generated__/a.ts"],
    "vendored": ["third_party/x/a.c"],
}  # fmt: skip
NOISE = [
    "package-lock.json", "Cargo.lock", "composer.lock", "Podfile.lock", "Package.resolved",
    "packages.lock.json", "mix.lock", "pubspec.lock", "go.sum", "gradle.lockfile",
    "a.png", "a.woff2", "fonts/a.ttf", ".idea/workspace.xml", "obj/project.assets.json",
]  # fmt: skip


def test_default_file_set_reads_the_common_languages_and_skips_build_output():
    fs = profiles.fileset_for(None, config.load_scan_defaults(ROOT))
    assert [p for p in READ if not fs.reads(p)] == []
    assert [p for p in NOT_READ if fs.reads(p)] == []
    for kind, paths in KINDS.items():
        assert [p for p in paths if not fs.matches(p, kind)] == [], kind
    assert fs.kind("src/main/java/Contest.java") is None  # `*Test.*` needs the capital T
    assert [p for p in NOISE if not any(profiles.glob_matcher(g)(p) for g in fs.noise)] == []


def test_generated_header_markers():
    fs = profiles.fileset_for(None, config.load_scan_defaults(ROOT))
    for head in (
        "// Code generated by protoc-gen-go. DO NOT EDIT.",
        "# @generated by tool",
        "// <auto-generated/>",
        "/* This file was automatically generated */",
        "// This file is generated. Changes will be lost.",
    ):
        assert fs.has_generated_marker([head, "x"]), head
    assert not fs.has_generated_marker(["# Generates the weekly report.", "x = 1"])


# --- the file type tables -----------------------------------------------------------------------


def test_every_language_extension_has_a_highlight_name_and_comment_prefixes():
    types = config.load_file_types(ROOT)
    exts = {
        e for raw in config.load_languages(ROOT)["languages"].values() for e in raw["extensions"]
    }
    q = yaml.safe_load((ROOT / "config" / "queries" / "languages.yaml").read_text())
    exts |= {e for raw in q["languages"].values() for e in raw["extensions"]}
    assert sorted(e for e in exts if e not in types["highlight"]) == []
    assert sorted(e for e in exts if e not in types["comment_prefixes"]) == []


def test_file_types_cover_the_common_stacks():
    types = config.load_file_types(ROOT)
    hl = types["highlight"]
    for ext, name in {".cs": "csharp", ".php": "php", ".swift": "swift", ".kt": "kotlin",
                      ".scala": "scala", ".ex": "elixir", ".dart": "dart", ".vue": "vue",
                      ".h": "c", ".hpp": "cpp", ".proto": "proto", ".tf": "terraform",
                      ".graphql": "graphql", ".scss": "scss", ".xml": "xml"}.items():  # fmt: skip
        assert hl.get(ext) == name, ext
    for word in ("csproj", "gradle", "sum", "mod"):
        assert word in config.load_file_types(ROOT)["file_words"], word
    for m in ("composer.json", "Package.swift", "*.csproj", "build.gradle*", "mix.exs",
              "pubspec.yaml", "CMakeLists.txt", "pom.xml", "go.mod"):  # fmt: skip
        assert m in types["manifests"], m
    for base in ("composer.json", "pom.xml", "build.gradle", "gemfile", "package.swift"):
        assert base in types["noise_basenames"], base
    # No name here is about one project: every entry is a file name of a public tool.
    assert all(n == n.lower() for n in types["noise_basenames"])


def test_shipped_languages_cover_the_grammars_with_a_query():
    langs = config.load_languages(ROOT)["languages"]
    assert {"python", "clojure", "typescript", "go", "rust", "java", "ruby", "kotlin",
            "csharp", "php", "swift"} <= set(langs)  # fmt: skip
    text = (ROOT / "config" / "languages.yaml").read_text()
    assert "defendpoint" not in text  # one project's macro: it belongs in that repo's profile


def _core(tmp_path, files) -> list[str]:
    r = build_history_repo(tmp_path / "r", [("one", files, "2026-01-01T10:00:00+00:00")])
    t0 = gitq.commit_time(r.path, "main")
    found = candidates.mine(r.path, "main", t0, {}, AnalysisSettings())
    return [f"{c['path']}: {c['why']}" for c in found if c["tag"] == "core"]


def test_kotlin_imports_resolve_to_files(tmp_path):
    base = "src/main/kotlin/com/acme"
    files = {
        f"{base}/util/Money.kt": "package com.acme.util\n\nclass Money(val cents: Long)\n",
        f"{base}/a/Cart.kt": "package com.acme.a\n\nimport com.acme.util.Money\n\nclass Cart\n",
        f"{base}/b/Bill.kt": "package com.acme.b\n\nimport com.acme.util.Money\n\nclass Bill\n",
    }
    core = _core(tmp_path, files)
    assert len(core) == 1 and core[0].startswith(f"{base}/util/Money.kt: imported by 2 files")


def test_php_require_resolves_to_files(tmp_path):
    files = {
        "lib/money.php": "<?php\n\nfunction cents($x)\n{\n    return $x;\n}\n",
        "a.php": "<?php\n\nrequire_once __DIR__ . '/lib/money.php';\n",
        "b.php": "<?php\n\nrequire 'lib/money.php';\n",
    }
    core = _core(tmp_path, files)
    assert len(core) == 1 and core[0].startswith("lib/money.php: imported by 2 files")
