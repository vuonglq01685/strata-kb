from pathlib import Path

import pytest

from center_kb.codeingest import core
from center_kb.codeingest.extractors import api as api_ext
from center_kb.codeingest.extractors import integrations as int_ext
from center_kb.codeingest.extractors import tree as tree_ext
from tests.fixtures_coderepo import build_code_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return build_code_repo(tmp_path)


def _opts(root: Path, **kw):
    return core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb",
        doc_id="demo-code", repo_id="demo", **kw
    )


def _by_id(result: core.ExtractResult) -> dict[str, core.CodeSection]:
    return {s.id: s for s in result.sections}


class TestTreeExtractor:
    def test_always_detects(self, repo):
        assert tree_ext.TreeExtractor().detect(repo) is True

    def test_emits_a_single_struct_tree_section(self, repo):
        sections = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))
        assert list(sections) == ["struct.tree"]
        assert sections["struct.tree"].group == "structure"
        assert sections["struct.tree"].summary

    def test_lists_real_directories_and_ignores_noise(self, repo):
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        body = s.l2_md + s.l3_md
        assert "src/airspace" in body
        assert "web" in body
        assert "node_modules" not in body
        assert "__pycache__" not in body

    def test_l3_has_no_pipe_table(self, repo):
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        assert "|" not in s.l3_md
        assert s.l3_md.lstrip().startswith("```")

    def test_paths_use_forward_slashes(self, repo):
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        assert "\\" not in s.l2_md + s.l3_md

    def test_listing_is_alphabetically_sorted(self, repo):
        # Pins the one property this task uniquely owns: every directory
        # and file listing is sorted, not just filtered. Without the
        # sort() calls in walk_tree(), os.walk's raw (OS-dependent) order
        # would leak through here.
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        body = s.l2_md + s.l3_md
        assert body.index("- Dockerfile") < body.index("- docker-compose.yml")
        assert body.index("__init__.py") < body.index("service.py")
        top_level_dirs = [
            ln for ln in s.l2_md.splitlines() if ln.startswith("- ") and ln.endswith("/")
        ]
        assert top_level_dirs == ["- .github/", "- db/", "- src/", "- web/"]

    def test_l3_marks_its_depth_cap(self, repo):
        # L2 announces its own cap ("Directory layout (depth 2):"); L3 must
        # too, or the summary's whole-tree counts and this fenced listing
        # would silently disagree on a repo nested deeper than 4 levels.
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        assert "capped at depth 4" in s.l3_md

    def test_prunes_non_default_kb_dir(self, repo):
        kb_dir = repo / "docs" / "kb"
        (kb_dir / "demo-code").mkdir(parents=True)
        (kb_dir / "demo-code" / "structure.md").write_text("stub\n", encoding="utf-8")
        opts = core.CodeIngestOptions(
            repo_root=repo, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo"
        )
        s = _by_id(tree_ext.TreeExtractor().extract(repo, opts))["struct.tree"]
        body = s.l2_md + s.l3_md
        assert "docs/kb" not in body
        assert "structure.md" not in body
        assert "docs" in body  # only the kb subtree is pruned, not its parent

    def test_prunes_relative_kb_dir(self, repo):
        (repo / "docs" / "kb" / "demo-code").mkdir(parents=True)
        (repo / "docs" / "kb" / "demo-code" / "structure.md").write_text(
            "stub\n", encoding="utf-8"
        )
        opts = core.CodeIngestOptions(
            repo_root=repo, kb_dir=Path("docs") / "kb",
            doc_id="demo-code", repo_id="demo",
        )
        s = _by_id(tree_ext.TreeExtractor().extract(repo, opts))["struct.tree"]
        body = s.l2_md + s.l3_md
        assert "docs/kb" not in body
        assert "structure.md" not in body


from center_kb.codeingest.extractors import deps as deps_ext


class TestDepsExtractor:
    def test_detects_when_any_manifest_exists(self, repo, tmp_path):
        assert deps_ext.DepsExtractor().detect(repo) is True
        empty = tmp_path / "empty"
        empty.mkdir()
        assert deps_ext.DepsExtractor().detect(empty) is False

    def test_one_section_per_ecosystem(self, repo):
        sections = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))
        assert set(sections) == {"dep.python", "dep.node", "dep.java"}
        for s in sections.values():
            assert s.group == "deps"
            assert s.summary

    def test_python_deps_are_listed_with_constraints(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.python"]
        assert "fastapi" in s.l2_md
        assert "fastapi>=0.110" in s.l3_md

    def test_node_separates_direct_from_dev_dependencies(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.node"]
        assert "react" in s.l2_md
        assert "eslint" in s.l3_md

    def test_java_deps_come_from_pom_xml(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.java"]
        assert "spring-boot-starter-web" in s.l3_md

    def test_frameworks_are_detected_for_frontend_and_backend(self, repo):
        sections = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))
        assert "FastAPI" in sections["dep.python"].l2_md
        assert "React" in sections["dep.node"].l2_md
        assert "Spring Boot" in sections["dep.java"].l2_md

    def test_dependencies_are_sorted_deterministically(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.python"]
        assert s.l3_md.index("fastapi") < s.l3_md.index("pydantic")

    def test_dependencies_are_sorted_regardless_of_source_order(self, repo):
        # The fixture's own pyproject.toml lists fastapi before pydantic in
        # BOTH source order and alphabetical order, so the test above would
        # still pass even with sorting removed entirely. This adds a
        # manifest whose declaration order is reverse-alphabetical, so only
        # genuine sorting (not accidental source-order pass-through) can
        # make this assertion hold.
        (repo / "requirements-extra.txt").write_text(
            "zzz-pkg>=1.0\naaa-pkg>=1.0\n", encoding="utf-8"
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.python"]
        assert s.l3_md.index("aaa-pkg") < s.l3_md.index("zzz-pkg")

    def test_l3_has_no_pipe_table(self, repo):
        for s in deps_ext.DepsExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    def test_unparseable_manifest_warns_and_does_not_crash(self, repo):
        (repo / "pom.xml").write_text("<project><dependencies>", encoding="utf-8")
        result = deps_ext.DepsExtractor().extract(repo, _opts(repo))
        assert any("pom.xml" in w for w in result.warnings)
        assert {"dep.python", "dep.node"} <= {s.id for s in result.sections}

    def test_case_colliding_names_sort_by_exact_name_not_hash_order(self, repo):
        # Review Finding 1: the old key (name.lower(), constraint) ties
        # completely on two names differing only in case, so `sorted()`'s
        # stability just preserved `set(pairs)`'s hash-order-dependent
        # iteration for the tie. Verified empirically (see task-B3-report.md
        # fix log) that "Newtonsoft.Json" vs "newtonsoft.json" flips order
        # across PYTHONHASHSEED 0/2/4 under the old key and is stable under
        # the new one. Comparing the raw (case-sensitive) name after the
        # lowercase key breaks the tie the same way on every run/process.
        (repo / "A.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
            '<PackageReference Include="Newtonsoft.Json" Version="13.0.3" />'
            "</ItemGroup></Project>\n",
            encoding="utf-8",
        )
        (repo / "B.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
            '<PackageReference Include="newtonsoft.json" Version="13.0.3" />'
            "</ItemGroup></Project>\n",
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.dotnet"]
        assert s.l3_md.index("Newtonsoft.Json") < s.l3_md.index("newtonsoft.json")

    def test_wrong_shaped_manifest_does_not_destroy_the_whole_ecosystem(self, repo):
        # Review Finding 2: a wrong-shaped (not malformed-syntax) top-level
        # manifest object used to bypass every per-file try/except and
        # unwind to extract()'s blanket handler, silently dropping every
        # *other* manifest for that ecosystem too (here, web/package.json's
        # real `react` dependency).
        (repo / "package.json").write_text("[]\n", encoding="utf-8")
        (repo / "pyproject.toml").write_text('project = "oops"\n', encoding="utf-8")
        result = deps_ext.DepsExtractor().extract(repo, _opts(repo))
        sections = _by_id(result)
        assert "react" in sections["dep.node"].l2_md
        assert any("package.json" in w for w in result.warnings)
        assert any("pyproject.toml" in w for w in result.warnings)

    def test_gradle_coordinates_split_into_name_and_version(self, repo):
        # Review Finding 4: `group:artifact:version` used to be stored
        # unsplit as the "name", so the same library got recognised as a
        # framework via pom.xml but not via build.gradle.
        (repo / "build.gradle").write_text(
            "dependencies {\n"
            "    implementation 'io.quarkus:quarkus-core:3.5.0'\n"
            "}\n",
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.java"]
        assert "quarkus-core 3.5.0" in s.l3_md
        assert "Quarkus" in s.l2_md

    def test_l2_table_escapes_pipe_characters_in_constraints(self, repo):
        # Review Finding 5: an OR-range constraint (Composer's `^6.0|^7.0`,
        # npm's `^17 || ^18`) contains an ordinary "|" that, unescaped,
        # reads as an extra column delimiter in the L2 Markdown table.
        (repo / "composer.json").write_text(
            '{"require": {"symfony/framework-bundle": "^6.0|^7.0"}}\n',
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.php"]
        row = next(ln for ln in s.l2_md.splitlines() if "symfony" in ln)
        assert "\\|" in row
        assert row.count("|") == 4  # 2 column delimiters + 2 real cells, no extra column

    def test_dotnet_deps_come_from_csproj(self, repo):
        # Review Finding 6: dotnet had zero test coverage.
        (repo / "App.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="Microsoft.AspNetCore.App" Version="8.0.0" />\n'
            "  </ItemGroup>\n"
            "</Project>\n",
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.dotnet"]
        assert "Microsoft.AspNetCore.App 8.0.0" in s.l3_md
        assert "ASP.NET Core" in s.l2_md

    def test_go_deps_come_from_go_mod(self, repo):
        # Review Finding 6: go had zero test coverage.
        (repo / "go.mod").write_text(
            "module example.com/svc\n\n"
            "go 1.22\n\n"
            "require (\n"
            "    github.com/gin-gonic/gin v1.9.1\n"
            ")\n",
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.go"]
        assert "github.com/gin-gonic/gin v1.9.1" in s.l3_md

    def test_go_mod_skips_comment_only_lines_in_require_block(self, repo):
        # Review Finding 7: a `//` comment-only line inside `require ( ... )`
        # used to be split into a bogus ("//", "pinned") dependency pair.
        (repo / "go.mod").write_text(
            "module example.com/svc\n\n"
            "require (\n"
            "    // pinned for CVE-2024-1\n"
            "    github.com/gin-gonic/gin v1.9.1\n"
            ")\n",
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.go"]
        assert "pinned" not in s.l3_md
        assert s.summary == "1 direct Go dependencies."

    def test_php_deps_come_from_composer_json(self, repo):
        # Review Finding 6: php had zero test coverage.
        (repo / "composer.json").write_text(
            '{"require": {"symfony/framework-bundle": "^6.0"},'
            ' "require-dev": {"phpunit/phpunit": "^10.0"}}\n',
            encoding="utf-8",
        )
        sections = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))
        s = sections["dep.php"]
        assert "symfony/framework-bundle" in s.l2_md
        assert "phpunit/phpunit" in s.l3_md
        assert "Symfony" in s.l2_md

    def test_vendored_node_modules_package_json_is_ignored(self, repo):
        # Review Finding 6: nothing pinned that a vendored package.json
        # inside node_modules/ (installed dependencies, not the project's
        # own) is excluded — output must not depend on whether
        # node_modules/ happens to be installed.
        (repo / "node_modules" / "left-pad" / "package.json").write_text(
            '{"name": "left-pad", "dependencies": {"should-not-appear": "1.0.0"}}\n',
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.node"]
        assert "should-not-appear" not in s.l2_md + s.l3_md

    def test_requirements_txt_skips_options_and_inline_comments(self, repo):
        # Review Finding 8: only "#", "-r", "-e" were skipped, so a pip
        # option line like "--extra-index-url ..." became a bogus
        # dependency, and a trailing inline comment leaked into the
        # constraint.
        (repo / "requirements-extra.txt").write_text(
            "--extra-index-url https://example.com/simple\n"
            "httpx>=0.27  # test client\n",
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.python"]
        assert "httpx>=0.27" in s.l3_md
        assert "extra-index-url" not in s.l3_md
        assert "test client" not in s.l3_md

    # -- task review, Important 2: credentials committed in source are
    #    republished verbatim, including into a PEP 508 direct-URL
    #    requirement and an npm git dependency. ------------------------

    def test_python_direct_url_dependency_credential_is_redacted(self, tmp_path):
        # A PEP 508 direct-URL requirement is the normal way a private
        # package is declared -- the credential's precondition is that it
        # was already committed in plaintext, but .kb/ republishes the
        # whole KB to the federation hub, an audience wider than the
        # source repo.
        root = tmp_path / "direct-url"
        root.mkdir()
        (root / "pyproject.toml").write_text(
            "[project]\n"
            'dependencies = ["mypkg @ git+https://x-token:S3CR3TV4LUE@github.com/o/r.git"]\n',
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(root, _opts(root)))["dep.python"]
        assert "S3CR3TV4LUE" not in s.l2_md
        assert "S3CR3TV4LUE" not in s.l3_md
        assert "git+https://***@github.com/o/r.git" in s.l3_md

    def test_npm_git_dependency_credential_is_redacted(self, tmp_path):
        root = tmp_path / "npm-git-dep"
        root.mkdir()
        (root / "package.json").write_text(
            '{"dependencies": {"mypkg": '
            '"git+https://x-token:S3CR3TV4LUE@github.com/o/r.git"}}',
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(root, _opts(root)))["dep.node"]
        assert "S3CR3TV4LUE" not in s.l2_md
        assert "S3CR3TV4LUE" not in s.l3_md
        assert "git+https://***@github.com/o/r.git" in s.l3_md


class TestFrameworkLookup:
    @pytest.mark.parametrize(
        "dep,expected",
        [
            ("spring-boot-starter-web", "Spring Boot"),
            ("Microsoft.AspNetCore.App", "ASP.NET Core"),
            ("fastapi", "FastAPI"),
            ("django", "Django"),
            ("flask", "Flask"),
            ("react", "React"),
            ("next", "Next.js"),
            ("@angular/core", "Angular"),
            ("vue", "Vue"),
        ],
    )
    def test_known_frameworks_map_to_labels(self, dep, expected):
        assert expected in deps_ext.detect_frameworks([dep])

    def test_unknown_dependency_yields_nothing(self):
        assert deps_ext.detect_frameworks(["left-pad"]) == []

    @pytest.mark.parametrize(
        "dep",
        [
            "reactive-streams",  # a real Maven artifactId (org.reactivestreams)
            "expressive",
            "nextcloud-client",
            "flasky",
            "celeryd",
        ],
    )
    def test_prefix_match_requires_a_name_boundary(self, dep):
        # Review Finding 3: `startswith()` alone matched a `FRAMEWORKS`
        # prefix against any longer name that merely began with it, so a
        # Java dependency on `reactive-streams` was mislabeled as React.
        assert deps_ext.detect_frameworks([dep]) == []


from center_kb.codeingest.extractors import services as svc_ext


class TestServicesExtractor:
    def test_detects_compose_dockerfile_or_k8s(self, repo, tmp_path):
        assert svc_ext.ServicesExtractor().detect(repo) is True
        empty = tmp_path / "empty2"
        empty.mkdir()
        assert svc_ext.ServicesExtractor().detect(empty) is False

    def test_one_section_per_compose_service(self, repo):
        sections = _by_id(svc_ext.ServicesExtractor().extract(repo, _opts(repo)))
        assert "svc.airspace-service" in sections
        assert "svc.postgres" in sections
        for s in sections.values():
            assert s.group == "services"

    def test_section_ids_have_no_whitespace(self, repo):
        for s in svc_ext.ServicesExtractor().extract(repo, _opts(repo)).sections:
            assert " " not in s.id and "\t" not in s.id

    def test_records_image_ports_and_depends_on(self, repo):
        s = _by_id(svc_ext.ServicesExtractor().extract(repo, _opts(repo)))["svc.airspace-service"]
        body = s.l2_md + s.l3_md
        assert "airspace:1.0" in body
        assert "8080" in body
        assert "postgres" in body

    def test_environment_keys_only_never_values(self, repo):
        s = _by_id(svc_ext.ServicesExtractor().extract(repo, _opts(repo)))["svc.airspace-service"]
        body = s.l2_md + s.l3_md
        assert "KAFKA_BROKER_URL" in body
        assert "kafka:9092" not in body
        assert "postgres://db/airspace" not in body

    def test_dockerfile_only_repo_yields_one_service_named_after_the_repo(self, tmp_path):
        root = tmp_path / "solo"
        root.mkdir()
        (root / "Dockerfile").write_text("FROM node:20\nEXPOSE 3000\n", encoding="utf-8")
        sections = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))
        assert "svc.demo" in sections          # opts.repo_id == "demo"
        assert "3000" in sections["svc.demo"].l2_md

    def test_k8s_deployment_is_picked_up(self, tmp_path):
        root = tmp_path / "k8s"
        (root / "deploy").mkdir(parents=True)
        (root / "deploy" / "app.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: notify-service\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: notify\n          image: notify:2.1\n"
            "          ports:\n            - containerPort: 9000\n",
            encoding="utf-8",
        )
        sections = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))
        assert "svc.notify-service" in sections
        assert "notify:2.1" in sections["svc.notify-service"].l3_md

    def test_services_are_sorted_by_name(self, repo):
        ids = [s.id for s in svc_ext.ServicesExtractor().extract(repo, _opts(repo)).sections]
        assert ids == sorted(ids)

    def test_services_are_sorted_regardless_of_source_order(self, tmp_path):
        # The fixture's own compose file declares "airspace-service" before
        # "postgres" in BOTH source order and alphabetical order, so
        # test_services_are_sorted_by_name above would still pass even with
        # every sort call removed. This compose file declares its services
        # in reverse-alphabetical order, so only genuine sorting (not
        # accidental source-order pass-through) can make this hold.
        root = tmp_path / "unsorted"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  zzz-service:\n    image: zzz:1.0\n"
            "  aaa-service:\n    image: aaa:1.0\n",
            encoding="utf-8",
        )
        ids = [s.id for s in svc_ext.ServicesExtractor().extract(root, _opts(root)).sections]
        assert ids == ["svc.aaa-service", "svc.zzz-service"]

    def test_services_are_sorted_across_readers(self, tmp_path):
        # The test above only exercises _read_compose()'s own internal
        # `sorted(services)` call — a single compose file is already
        # alphabetical by the time it leaves that reader, so it would
        # still pass even if extract()'s own final
        # `sorted(merged, key=lambda r: r.name)` were deleted. Here compose
        # contributes "zzz-service" and k8s contributes "aaa-service";
        # extract() appends compose's records before k8s's, so only a real
        # cross-reader sort (not either reader's own internal one) can put
        # aaa-service first.
        root = tmp_path / "cross"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  zzz-service:\n    image: zzz:1.0\n", encoding="utf-8"
        )
        (root / "deploy").mkdir()
        (root / "deploy" / "app.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: aaa-service\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: aaa\n          image: aaa:1.0\n",
            encoding="utf-8",
        )
        ids = [s.id for s in svc_ext.ServicesExtractor().extract(root, _opts(root)).sections]
        assert ids == ["svc.aaa-service", "svc.zzz-service"]

    def test_l3_has_no_pipe_table(self, repo):
        for s in svc_ext.ServicesExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    def test_malformed_compose_warns_and_does_not_crash(self, tmp_path):
        root = tmp_path / "bad"
        root.mkdir()
        (root / "docker-compose.yml").write_text("services: [", encoding="utf-8")
        (root / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert any("docker-compose.yml" in w for w in result.warnings)
        assert result.sections  # the Dockerfile path still produced a service

    # --- fix round: task review findings -----------------------------------

    def test_environment_list_form_keeps_only_keys(self, tmp_path):
        # Review Finding 8: the brief names both the mapping form (already
        # covered by test_environment_keys_only_never_values, against the
        # shared fixture) and the `KEY=value` list form, but only the
        # mapping form had a test — exactly where the Critical finding
        # below lived undetected.
        root = tmp_path / "envlist"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  api:\n    image: api:1.0\n"
            "    environment:\n"
            "      - DB_PASSWORD=hunter2\n"
            "      - LOG_LEVEL=debug\n",
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.api"]
        body = s.l2_md + s.l3_md
        assert "DB_PASSWORD" in body
        assert "LOG_LEVEL" in body
        assert "hunter2" not in body
        assert "debug" not in body

    def test_environment_list_entry_with_colon_does_not_leak_its_value(self, tmp_path):
        # Critical review finding: YAML parses a list entry containing
        # ": " but no "=" as a single-pair *mapping*, not a string (e.g.
        # `- SECRET_KEY: s3cr3t`). The old code fell through to `str(item)`
        # on any non-string item, stringifying the whole {key: value} pair
        # -- including the secret value -- straight into env_keys and from
        # there into l2_md/l3_md. This is exactly the shape that leaked.
        root = tmp_path / "envcolon"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  api:\n    image: api:1.0\n"
            "    environment:\n"
            "      - DB_PASSWORD=hunter2\n"
            "      - SECRET_KEY: s3cr3t\n",
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.api"]
        body = s.l2_md + s.l3_md
        assert "SECRET_KEY" in body
        assert "s3cr3t" not in body
        assert "hunter2" not in body

    def test_distinct_names_that_slugify_to_the_same_id_do_not_crash(self, tmp_path):
        # Important Finding 2: compose's "api_gateway" and a k8s
        # Deployment's "api-gateway" both slug to "api-gateway" (underscores
        # are legal in compose; DNS-1123 forbids them in k8s -- normal
        # spelling drift, not a malformed manifest). Deduping on the raw
        # name let both survive, so core.run()'s duplicate-id guard would
        # crash on a legitimate repo.
        root = tmp_path / "collision"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  api_gateway:\n    image: gw:1.0\n", encoding="utf-8"
        )
        (root / "deploy").mkdir()
        (root / "deploy" / "app.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: api-gateway\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: gw\n          image: gw:2.0\n",
            encoding="utf-8",
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert [s.id for s in result.sections] == ["svc.api-gateway"]

    def test_unicode_service_name_yields_a_nonempty_parseable_heading(self, tmp_path):
        # Important Finding 3: slugify() (ASCII-fold, non-ASCII dropped)
        # collapses a fully non-Latin name to an empty string, giving
        # id="svc." and title="" -- an unparseable "## svc. " heading that
        # made `kb build` fail. slugify_id() keeps non-ASCII scripts intact.
        from center_kb import mdutils

        root = tmp_path / "unicode"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  認証サービス:\n"
            "    image: auth:1.0\n",
            encoding="utf-8",
        )
        sections = svc_ext.ServicesExtractor().extract(root, _opts(root)).sections
        assert len(sections) == 1
        section = sections[0]
        assert section.id != "svc."
        assert " " not in section.id
        assert section.title  # CodeSection requires a non-empty title
        heading = f"## {section.id} {section.title}"
        assert mdutils._HEADING_RE.match(heading) is not None

    def test_service_name_with_whitespace_produces_a_whitespace_free_id(self, tmp_path):
        # Minor Finding: test_section_ids_have_no_whitespace (above) is
        # vacuous against every fixture used in this class -- none of
        # their names contain whitespace, so it would still pass even with
        # id generation reduced to a bare f"svc.{name}". This name has a
        # real space in it.
        root = tmp_path / "space"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            'services:\n  "my service":\n    image: x:1.0\n', encoding="utf-8"
        )
        sections = svc_ext.ServicesExtractor().extract(root, _opts(root)).sections
        assert len(sections) == 1
        assert " " not in sections[0].id
        assert sections[0].id == "svc.my-service"

    def test_title_and_description_and_summary_use_the_real_name_not_the_slug(self, tmp_path):
        # Important Finding 4: only the id needs mdutils._HEADING_RE's
        # no-whitespace token -- the title half of that heading line
        # accepts whitespace freely. Slugifying title/description/summary
        # too meant the real, grep-able name ("Airspace.Api") appeared
        # nowhere in the emitted document, only its slug ("airspace-api").
        root = tmp_path / "realname"
        root.mkdir()
        (root / "App.sln").write_text(
            'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Airspace.Api", '
            '"Airspace.Api\\Airspace.Api.csproj", '
            '"{11111111-1111-1111-1111-111111111111}"\n'
            "EndProject\n",
            encoding="utf-8",
        )
        sections = svc_ext.ServicesExtractor().extract(root, _opts(root)).sections
        assert len(sections) == 1
        s = sections[0]
        assert s.id == "svc.airspace-api"
        assert s.title == "Airspace.Api"
        assert "Airspace.Api" in s.l2_md
        assert "Airspace.Api" in s.summary

    def test_sln_skips_solution_folders(self, tmp_path):
        # Important Finding 6: _SLN_PROJECT_RE matched every
        # `Project(...)` line, including Solution Folder pseudo-projects
        # (project-type GUID {2150E333-8FDC-42A3-9474-1A3956D46DE4}), so a
        # .NET repo minted permanent public join keys like svc.src and
        # svc.solution-items.
        root = tmp_path / "slnfolders"
        root.mkdir()
        (root / "App.sln").write_text(
            'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Airspace.Api", '
            '"Airspace.Api\\Airspace.Api.csproj", '
            '"{11111111-1111-1111-1111-111111111111}"\n'
            "EndProject\n"
            'Project("{2150E333-8FDC-42A3-9474-1A3956D46DE4}") = "src", "src", '
            '"{22222222-2222-2222-2222-222222222222}"\n'
            "EndProject\n"
            'Project("{2150E333-8FDC-42A3-9474-1A3956D46DE4}") = "Solution Items", '
            '"Solution Items", "{33333333-3333-3333-3333-333333333333}"\n'
            "EndProject\n",
            encoding="utf-8",
        )
        ids = [s.id for s in svc_ext.ServicesExtractor().extract(root, _opts(root)).sections]
        assert ids == ["svc.airspace-api"]

    def test_dedupe_prefers_compose_and_warns_only_on_image_disagreement(self, tmp_path):
        # Important Finding 5 (part 1): _dedupe had zero test coverage for
        # either the brief's compose-preference rule or its
        # warn-only-on-disagreement rule.
        root = tmp_path / "prefercompose"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  shared:\n    image: compose-image:1.0\n", encoding="utf-8"
        )
        (root / "deploy").mkdir()
        (root / "deploy" / "app.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: shared\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: shared\n          image: k8s-image:2.0\n",
            encoding="utf-8",
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        s = _by_id(result)["svc.shared"]
        assert "compose-image:1.0" in s.l2_md
        assert "k8s-image:2.0" not in s.l2_md
        assert any("shared" in w and "compose-image:1.0" in w for w in result.warnings)

    def test_dedupe_does_not_warn_when_images_agree(self, tmp_path):
        # Important Finding 5 (part 2): the "only" in warn-only-on-
        # disagreement needs its own test -- two sources for the same
        # service with the SAME image must not warn.
        root = tmp_path / "agreeing"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  shared:\n    image: same:1.0\n", encoding="utf-8"
        )
        (root / "deploy").mkdir()
        (root / "deploy" / "app.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: shared\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: shared\n          image: same:1.0\n",
            encoding="utf-8",
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert result.warnings == []

    def test_dedupe_prefers_a_record_with_a_real_image_over_an_earlier_empty_one(self, tmp_path):
        # Important Finding 5 (part 3): reproduced a `01-service.yaml` /
        # `02-deployment.yaml` layout -- a bare k8s `Service` (no
        # containers, so image="") listed before its `Deployment` (the
        # real image). First-occurrence-wins used to keep the empty-image
        # Service and silently discard the Deployment's real image.
        root = tmp_path / "emptyimage"
        (root / "deploy").mkdir(parents=True)
        (root / "deploy" / "01-service.yaml").write_text(
            "apiVersion: v1\nkind: Service\n"
            "metadata:\n  name: notify\n"
            "spec:\n  ports:\n    - port: 80\n",
            encoding="utf-8",
        )
        (root / "deploy" / "02-deployment.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: notify\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: notify\n          image: notify:2.1\n",
            encoding="utf-8",
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        s = _by_id(result)["svc.notify"]
        assert "notify:2.1" in s.l2_md

    def test_compose_yaml_preferred_filename_is_read(self, tmp_path):
        # Important Finding 7 / Ruling R27: "docker-compose*.y*ml" alone
        # misses "compose.yaml", the Compose Specification's preferred
        # filename and what Docker Compose v2 scaffolds by default -- on
        # such a repo compose used to contribute nothing and the
        # Dockerfile fallback fired instead, emitting the wrong join key.
        root = tmp_path / "modern"
        root.mkdir()
        (root / "compose.yaml").write_text(
            "services:\n  web:\n    image: web:1.0\n", encoding="utf-8"
        )
        assert svc_ext.ServicesExtractor().detect(root) is True
        sections = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))
        assert "svc.web" in sections

    def test_detect_ignores_a_directory_named_like_a_compose_or_sln_file(self, tmp_path):
        # Minor Finding: detect() used a bare any(root.glob(...)) with no
        # is_file() filter, so a directory (not a file) named like a
        # compose/sln file made detect() True while extract() -- which
        # does filter -- returned nothing.
        root = tmp_path / "dirtrap"
        (root / "docker-compose.yml").mkdir(parents=True)
        (root / "compose.yaml").mkdir()
        (root / "x.sln").mkdir()
        assert svc_ext.ServicesExtractor().detect(root) is False

    # --- fix round 2: task re-review findings ------------------------------

    def test_environment_dict_key_with_embedded_equals_does_not_leak_its_value(
        self, tmp_path
    ):
        # Critical review finding, still open after round 1: round 1's
        # fix split "KEY=value" *strings* on "=" but the sibling dict-item
        # branch (for a YAML `- KEY: value` shape) took the dict key
        # verbatim. A dict key can itself carry the "KEY=value" shape --
        # this happens whenever a "KEY=value" entry is immediately
        # followed by another ": "-bearing token on the same line, which
        # is exactly the reviewer's second reproduction and its "ordinary
        # compose content" example. Exercised through the real extractor
        # end-to-end and asserted on rendered l2_md/l3_md, not on
        # _env_keys_from()'s return value -- round 1's test happened to
        # only exercise the plain-string branch, which was already safe,
        # so it passed while this leak was live.
        root = tmp_path / "envleak2"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  api:\n    image: api:1.0\n"
            "    environment:\n"
            "      - CREDENTIALS=user:pass, note: internal\n"
            '      - CONFIG={"a": 1}\n'
            "      - LOG_FORMAT=json: pretty\n"
            "      - DB_PASSWORD=hunter2: extra\n",
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.api"]
        body = s.l2_md + s.l3_md
        assert "hunter2" not in body
        assert "user:pass" not in body
        assert "pretty" not in body
        assert "internal" not in body
        assert "extra" not in body
        assert "json" not in body
        assert "CREDENTIALS" in body
        assert "DB_PASSWORD" in body
        assert "LOG_FORMAT" in body
        assert "CONFIG" in body

    def test_dedupe_fills_empty_image_without_discarding_other_fields(self, tmp_path):
        # New Important Finding (round 2): round 1's fix for "prefer a
        # non-empty image when the kept record's is empty" swapped in the
        # WHOLE later record instead of just filling the image field. A
        # compose service declared with `build:` instead of `image:` has
        # image="" but real ports/depends_on/environment; a k8s Deployment
        # that merely supplies the image must not erase them or
        # re-attribute provenance to itself.
        root = tmp_path / "buildonly"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  web:\n    build: .\n"
            '    ports: ["8080:8080"]\n'
            "    depends_on: [postgres]\n"
            "    environment:\n"
            "      KAFKA_BROKER_URL: kafka:9092\n",
            encoding="utf-8",
        )
        (root / "deploy").mkdir()
        (root / "deploy" / "web.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: web\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: web\n          image: web:9.9\n",
            encoding="utf-8",
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        s = _by_id(result)["svc.web"]
        assert "web:9.9" in s.l2_md
        assert "8080:8080" in s.l2_md
        assert "postgres" in s.l2_md
        assert "KAFKA_BROKER_URL" in s.l2_md
        assert "docker-compose.yml" in s.l2_md
        assert "deploy/web.yaml" not in s.l2_md

    def test_truncation_collision_keeps_both_services_distinct(self, tmp_path):
        # Controller Ruling R30: mdutils.slugify_id() truncates to 40
        # characters. "airspace-production-notification-worker-a" and
        # "...-worker-b" both truncate to
        # "airspace-production-notification-worker" -- deduping on the
        # truncated slug (round 1's approach) silently merged them into
        # one record, deleting one entirely with zero warnings.
        root = tmp_path / "truncation"
        (root / "deploy").mkdir(parents=True)
        (root / "deploy" / "a.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: airspace-production-notification-worker-a\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: worker-a\n          image: worker:1.0\n"
            "          ports:\n            - containerPort: 8001\n",
            encoding="utf-8",
        )
        (root / "deploy" / "b.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: airspace-production-notification-worker-b\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: worker-b\n          image: worker:2.0\n"
            "          ports:\n            - containerPort: 8002\n",
            encoding="utf-8",
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert len(result.sections) == 2
        ids = [s.id for s in result.sections]
        assert len(set(ids)) == 2
        bodies = [s.l2_md for s in result.sections]
        assert any("8001" in b for b in bodies)
        assert any("8002" in b for b in bodies)

    def test_truncation_collision_id_is_stable_when_a_sibling_is_removed(self, tmp_path):
        # Ruling R30 part 3: the disambiguation suffix must come only from
        # the service's own full normalized name, never from sibling
        # order or an index -- so removing an unrelated colliding sibling
        # must not change the id of the one that remains.
        def build(root, names):
            (root / "deploy").mkdir(parents=True)
            for i, name in enumerate(names):
                (root / "deploy" / f"{i}.yaml").write_text(
                    "apiVersion: apps/v1\nkind: Deployment\n"
                    f"metadata:\n  name: {name}\n"
                    "spec:\n  template:\n    spec:\n      containers:\n"
                    f"        - name: c\n          image: worker:{i}.0\n",
                    encoding="utf-8",
                )

        both_root = tmp_path / "both"
        build(
            both_root,
            [
                "airspace-production-notification-worker-a",
                "airspace-production-notification-worker-b",
            ],
        )
        one_root = tmp_path / "one"
        build(one_root, ["airspace-production-notification-worker-a"])

        both_ids = {
            s.title: s.id
            for s in svc_ext.ServicesExtractor().extract(both_root, _opts(both_root)).sections
        }
        one_ids = {
            s.title: s.id
            for s in svc_ext.ServicesExtractor().extract(one_root, _opts(one_root)).sections
        }
        a_name = "airspace-production-notification-worker-a"
        assert both_ids[a_name] == one_ids[a_name]

    def test_punctuation_only_name_does_not_ship_as_bare_svc(self, tmp_path):
        # Controller Ruling R31: a name made entirely of punctuation
        # (slugify_id() -> "") must not ship as the degenerate public
        # join key "svc.".
        root = tmp_path / "punctuation"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            'services:\n  "+++":\n    image: x:1.0\n', encoding="utf-8"
        )
        sections = svc_ext.ServicesExtractor().extract(root, _opts(root)).sections
        assert len(sections) == 1
        assert sections[0].id != "svc."
        assert len(sections[0].id) > len("svc.")

    def test_two_punctuation_only_names_do_not_silently_merge(self, tmp_path):
        # Ruling R31's second half: two different degenerate names (both
        # normalizing to "") must not be forced into the same record just
        # because they share an empty normalized form.
        root = tmp_path / "punctuation2"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            'services:\n  "+++":\n    image: a:1.0\n  "...":\n    image: b:1.0\n',
            encoding="utf-8",
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert len(result.sections) == 2
        ids = [s.id for s in result.sections]
        assert len(set(ids)) == 2

    def test_empty_compose_service_key_does_not_ship_as_bare_svc(self, tmp_path):
        # Ruling R31's residual case: an empty compose service key
        # (services: {"": {...}}) is the same degenerate shape as an
        # all-punctuation name and must use the same fallback.
        #
        # New Important review finding, round 3: this test (as it stood
        # after round 2) only asserted `id != "svc."` and dropped the
        # heading-parseability assertion round 1's
        # test_unicode_service_name_yields_a_nonempty_parseable_heading
        # used for precisely this property. That let a section ship whose
        # id LOOKED fine (id="svc.unnamed-<hash>") but whose title was
        # still "" (name.strip() == ""), rendering a title-less heading
        # "## svc.unnamed-<hash> " (trailing space, no title token).
        # After the F3 title-optional widening, `mdutils._HEADING_RE`
        # itself now matches that heading fine (its title capture group
        # is optional), so a regex match alone no longer catches a
        # regression here -- the invariant this test actually pins is
        # `CodeSection` requiring a non-empty title and `slice_section`
        # finding the real rendered content by id, not a syntactic
        # heading-format check. Restored here, plus an actual round-trip
        # through the real L2/L3 rendering `core.run()` uses
        # (`core._render_group` + `mdutils.slice_section`), not just a
        # regex match on a hand-assembled heading string.
        from center_kb import mdutils

        root = tmp_path / "emptykey"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            'services:\n  "":\n    image: x:1.0\n', encoding="utf-8"
        )
        sections = svc_ext.ServicesExtractor().extract(root, _opts(root)).sections
        assert len(sections) == 1
        section = sections[0]
        assert section.id != "svc."
        assert section.title  # CodeSection requires a non-empty title
        heading = f"## {section.id} {section.title}"
        assert mdutils._HEADING_RE.match(heading) is not None
        l2_rendered = core._render_group([section], "l2", "banner", "demo-code")
        assert mdutils.slice_section(l2_rendered, section.id) is not None
        l3_rendered = core._render_group([section], "l3", "banner", "demo-code")
        assert mdutils.slice_section(l3_rendered, section.id) is not None

    def test_whitespace_only_service_name_gets_a_titled_parseable_heading(self, tmp_path):
        # Same defect class as the empty-key case above, via a different
        # input: a name that is non-empty as a raw string but entirely
        # whitespace. `_safe_slug()`/`_dedupe_key()` treat this the same
        # as an empty name (their fallback triggers on `_normalize_name()`
        # being ""), but the title fallback added this round keys on
        # `name.strip()` specifically -- this input distinguishes "name
        # is falsy" from "name is all whitespace" and would catch an
        # implementation that checked `if not name` instead of
        # `if not name.strip()`.
        from center_kb import mdutils

        root = tmp_path / "whitespace"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            'services:\n  "   ":\n    image: x:1.0\n', encoding="utf-8"
        )
        sections = svc_ext.ServicesExtractor().extract(root, _opts(root)).sections
        assert len(sections) == 1
        section = sections[0]
        # `assert section.title` alone is vacuous here: a bare
        # all-whitespace string is still truthy in Python
        # (`bool("   ") == True`), so this wouldn't catch a broken
        # `title = record.name` fallback the way it would for a truly
        # empty name. `.strip()` makes the assertion mean what it says.
        assert section.title.strip()
        heading = f"## {section.id} {section.title}"
        assert mdutils._HEADING_RE.match(heading) is not None
        l2_rendered = core._render_group([section], "l2", "banner", "demo-code")
        assert mdutils.slice_section(l2_rendered, section.id) is not None

    def test_env_key_enumeration_top_level_mapping_with_embedded_equals(self, tmp_path):
        # CRITICAL review finding, round 3: _env_keys_from has (had)
        # THREE branches that can put a string into ServiceRecord.env_keys
        # -- the top-level `environment: {...}` mapping form
        # (services.py's `if isinstance(value, dict):` branch), the
        # list-of-strings form, and the list-of-dicts form. Round 1 fixed
        # the list-of-strings branch; round 2 fixed the list-of-dicts
        # branch; the top-level mapping branch was never touched, because
        # every env test written so far used the list form and so could
        # not reach it with a key that needed splitting. Reproduces the
        # reviewer's exact YAML (a mapping-form key that itself carries
        # the "KEY=value" shape, value null).
        root = tmp_path / "envleak3"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  api:\n    image: api:1.0\n"
            "    environment:\n"
            "      DB_PASSWORD=hunter2:\n"
            "      API_TOKEN=abc123:\n",
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.api"]
        body = s.l2_md + s.l3_md
        assert "hunter2" not in body
        assert "abc123" not in body
        assert "DB_PASSWORD" in body
        assert "API_TOKEN" in body

    def test_env_key_enumeration_top_level_mapping_round2_repro_moved_here(self, tmp_path):
        # Same top-level mapping branch, using round 2's exact repro
        # strings moved from the list form to the mapping form -- the
        # reviewer's second, byte-identical-leak reproduction for this
        # finding.
        root = tmp_path / "envleak3b"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  api:\n    image: api:1.0\n"
            "    environment:\n"
            '      CREDENTIALS=user:pass, note: internal\n'
            "      LOG_FORMAT=json: pretty\n"
            "      DB_PASSWORD=hunter2: extra\n",
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.api"]
        body = s.l2_md + s.l3_md
        assert "hunter2" not in body
        assert "user:pass" not in body
        assert "pretty" not in body
        assert "internal" not in body
        assert "extra" not in body
        assert "json" not in body
        assert "CREDENTIALS" in body
        assert "DB_PASSWORD" in body
        assert "LOG_FORMAT" in body

    def test_env_key_with_embedded_newline_does_not_break_the_table(self, tmp_path):
        # Originally a Minor review finding, round 3 (B4): `.strip()`
        # only trims leading/trailing whitespace, so a key containing an
        # embedded newline rendered across two lines inside the "Env
        # keys" table cell, corrupting the table with a malformed extra
        # row -- round 3's fix collapsed embedded whitespace instead of
        # trimming it, keeping the (collapsed) key.
        #
        # Ruling R40 (Task B7) supersedes that: the shared
        # `_envkeys.sanitize_env_key` now requires a candidate key to be
        # a clean identifier token *end to end*, or it is rejected
        # outright rather than collapsed-and-kept -- the same rule that
        # closes a Critical secret leak elsewhere (a `:`-delimited value
        # with no `=` at all being published whole) also means a key
        # that was never a single well-formed identifier, embedded
        # newline included, no longer survives sanitisation at all. The
        # table-corruption property this test exists to guard still
        # holds, more strongly: the malformed key contributes nothing.
        root = tmp_path / "envnewline"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  api:\n    image: api:1.0\n"
            "    environment:\n"
            '      "LINE1\\nLINE2": v\n',
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.api"]
        assert "LINE1" not in s.l2_md
        assert not any(line.strip() == "LINE2 |" for line in s.l2_md.splitlines())
        assert "| Env keys | none |" in s.l2_md

    def test_hash_fallback_namespace_collision_still_yields_unique_ids(self, tmp_path):
        # Minor review finding, round 3: _assign_slugs()'s R31 hash
        # fallback ("unnamed-<sha256[:8]>") can coincide with a REAL
        # service that happens to be named exactly that fallback string.
        # slugify_id("+++") normalizes to "" -> _safe_slug("+++") falls
        # back to "unnamed-29f5099b" (verified: hashlib.sha256(b"+++")
        # .hexdigest()[:8] == "29f5099b"). A second service literally
        # named "unnamed-29f5099b" collides with that fallback, and the
        # per-record disambiguation logic can't see this (it inspects one
        # record at a time) -- without a final cross-record uniqueness
        # pass this used to yield 2 sections sharing 1 id, which
        # core.run()'s duplicate-id guard turns into a hard crash.
        root = tmp_path / "hashcollision"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            'services:\n'
            '  "+++":\n    image: a:1.0\n'
            "  unnamed-29f5099b:\n    image: b:1.0\n",
            encoding="utf-8",
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert len(result.sections) == 2
        ids = [s.id for s in result.sections]
        assert len(set(ids)) == 2

    def test_colon_delimited_environment_entry_with_no_equals_does_not_leak_its_value(
        self, tmp_path
    ):
        # Critical (Ruling R40): the reviewer found this exact compose
        # file leaks "hunter2" through ServicesExtractor too, because
        # this module's `_env_keys_from` used to keep its own copy of
        # the sanitiser now shared via `_envkeys.py`. A list-string
        # `environment:` entry with no "=" at all used to pass through
        # `.split("=", 1)[0]` unchanged -- the *entire* string, including
        # the embedded credential, became the "key" and was published
        # verbatim to the rendered "Env keys" table row and the L3 YAML
        # dump. `_envkeys.sanitize_env_key` now requires the whole
        # candidate to be a bare identifier or rejects it outright, so
        # this malformed entry contributes nothing.
        root = tmp_path / "svc-colon-leak"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  cache:\n"
            "    image: redis:7\n"
            "    environment:\n"
            "      - REDIS_URL:redis://user:hunter2@cache\n",
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.cache"]
        blob = s.l2_md + s.l3_md
        assert "hunter2" not in blob
        assert "| Env keys | none |" in s.l2_md

    def test_dotted_and_hyphenated_env_keys_are_kept(self, tmp_path):
        # Ruling R41 (round 2 of the R40 fix): the first widened rule
        # was still narrower than the reviewer required -- a bare
        # identifier only, which silently dropped the canonical
        # Elasticsearch/Kibana compose shape (dotted keys) and any
        # hyphenated key, with no warning, exactly the false negative
        # the review caught. `_KEY_TOKEN_RE` now also accepts `.` and
        # `-`, so these real-world keys survive.
        root = tmp_path / "svc-dotted-hyphenated"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  search:\n"
            "    image: elasticsearch:8\n"
            "    environment:\n"
            "      - ES_JAVA_OPTS=-Xms512m -Xmx512m\n"
            "      - cluster.name=docker-cluster\n"
            "      - discovery.type=single-node\n"
            "      - xpack.security.enabled=false\n"
            "      - MY-APP_TOKEN=abc\n",
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.search"]
        for key in ("ES_JAVA_OPTS", "cluster.name", "discovery.type",
                    "xpack.security.enabled", "MY-APP_TOKEN"):
            assert key in s.l2_md, key
        assert "| Env keys | none |" not in s.l2_md


from center_kb.codeingest.extractors import commands as cmd_ext


class TestCommandsExtractor:
    def test_detects_when_any_command_source_exists(self, repo, tmp_path):
        assert cmd_ext.CommandsExtractor().detect(repo) is True
        empty = tmp_path / "empty3"
        empty.mkdir()
        assert cmd_ext.CommandsExtractor().detect(empty) is False

    def test_emits_purpose_sections(self, repo):
        sections = _by_id(cmd_ext.CommandsExtractor().extract(repo, _opts(repo)))
        assert {"cmd.build", "cmd.test", "cmd.lint"} <= set(sections)
        for s in sections.values():
            assert s.group == "commands"
            assert s.summary

    def test_ci_run_steps_win_over_local_scripts(self, repo):
        s = _by_id(cmd_ext.CommandsExtractor().extract(repo, _opts(repo)))["cmd.test"]
        # CI runs pytest; web/package.json runs vitest. CI is the source of truth.
        assert "pytest -q --cov=airspace" in s.l2_md
        assert "CI" in s.l2_md
        assert "vitest run" in s.l3_md          # kept as an alternative

    def test_ci_command_is_specifically_the_primary_not_just_present(self, repo):
        # Strengthens test_ci_run_steps_win_over_local_scripts above: that
        # test's assertions all pass even if the CI-over-local priority
        # were silently reversed, because a demoted CI candidate would
        # still show up somewhere in l2_md/l3_md as an *alternative* --
        # both the alternatives table (L2) and the alternatives block
        # (L3) render every non-primary candidate's command text too.
        # This test pins the one signal that actually distinguishes
        # "primary" from "merely present": the first line of l2_md, which
        # Step 4 fixes as `**Primary:** \`<command>\``.
        s = _by_id(cmd_ext.CommandsExtractor().extract(repo, _opts(repo)))["cmd.test"]
        primary_line = s.l2_md.splitlines()[0]
        assert "pytest -q --cov=airspace" in primary_line
        assert "vitest" not in primary_line

    def test_local_scripts_are_used_when_there_is_no_ci(self, tmp_path):
        root = tmp_path / "nocI"
        root.mkdir()
        (root / "package.json").write_text(
            '{"scripts": {"test": "jest", "build": "tsc"}}\n', encoding="utf-8"
        )
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert "jest" in sections["cmd.test"].l2_md
        assert "tsc" in sections["cmd.build"].l2_md

    def test_makefile_targets_are_collected(self, tmp_path):
        root = tmp_path / "mk"
        root.mkdir()
        (root / "Makefile").write_text(
            "test:\n\tpytest -q\n\nlint:\n\truff check .\n", encoding="utf-8"
        )
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert "make test" in sections["cmd.test"].l2_md
        assert "make lint" in sections["cmd.lint"].l2_md

    def test_l3_has_no_pipe_table(self, repo):
        for s in cmd_ext.CommandsExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    def test_no_section_when_a_purpose_has_no_command(self, tmp_path):
        root = tmp_path / "only-build"
        root.mkdir()
        (root / "package.json").write_text('{"scripts": {"build": "tsc"}}\n', encoding="utf-8")
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert "cmd.build" in sections
        assert "cmd.test" not in sections

    def test_run_command_is_emitted_for_the_fixture_repo(self, repo):
        # Finding 4 (task review round 1): cmd.run is one of the four
        # contracted section ids dev-execute/dev-handover read, and in the
        # shared fixture it only exists via an incidental side effect of
        # the R2 fold (web/package.json's "start" script body is "vite",
        # which alone carries no `run` keyword -- only the folded
        # "(npm run start)" invocation does). Pin its presence explicitly
        # so a later refactor that weakens the fold has something to trip.
        sections = _by_id(cmd_ext.CommandsExtractor().extract(repo, _opts(repo)))
        assert "cmd.run" in sections
        assert "vite" in sections["cmd.run"].l2_md

    def test_ci_working_directory_is_carried_into_the_source_label(self, tmp_path):
        # Finding 1 (task review round 1, controller ruling R33): a step
        # that sets `working-directory:` runs its command there, not at
        # the repo root. Losing that turns a subdirectory-only command
        # into one presented as root-runnable -- false confidence, not
        # just missing detail.
        root = tmp_path / "workdir"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n    steps:\n"
            "      - run: npm test\n"
            "        working-directory: web\n",
            encoding="utf-8",
        )
        s = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))["cmd.test"]
        assert "(in web/)" in s.l2_md
        assert "npm test" in s.l2_md.splitlines()[0]

    def test_ci_multiline_run_with_a_leading_cd_carries_the_directory(self, tmp_path):
        # Finding 1's other shape: a multi-line `run: |` block whose first
        # line is a standalone `cd <dir>` -- the reviewer's exact repro.
        # `cd web` itself still classifies to None and is dropped (the
        # brief's split-on-newlines behaviour is unchanged); only the
        # source label gains the directory the later lines actually run
        # in.
        root = tmp_path / "cdblock"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n    steps:\n"
            "      - run: |\n"
            "          cd web\n"
            "          npm ci\n"
            "          npm test\n",
            encoding="utf-8",
        )
        s = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))["cmd.test"]
        assert "(in web/)" in s.l2_md
        assert "npm test" in s.l2_md.splitlines()[0]
        assert "cd web" not in s.l2_md.splitlines()[0]

    def test_ci_run_as_a_list_warns_instead_of_disappearing_silently(self, tmp_path):
        # Finding 3: a `run:` that's a wrong-shaped value (here a YAML
        # list, e.g. from a typo'd flow-style step) used to be dropped
        # with zero warnings -- indistinguishable from a workflow that
        # legitimately has no commands.
        root = tmp_path / "runlist"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n    steps:\n      - run: [pytest, -q]\n",
            encoding="utf-8",
        )
        result = cmd_ext.CommandsExtractor().extract(root, _opts(root))
        assert result.sections == []
        assert any("ci.yml" in w for w in result.warnings)

    def test_ci_step_that_is_not_a_mapping_warns(self, tmp_path):
        # Finding 3's other shape: a step that isn't a mapping at all.
        root = tmp_path / "stepnotmap"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n    steps:\n      - just-a-string\n",
            encoding="utf-8",
        )
        result = cmd_ext.CommandsExtractor().extract(root, _opts(root))
        assert any("ci.yml" in w for w in result.warnings)

    def test_uses_only_step_does_not_warn(self, tmp_path):
        # The carve-out Finding 3 asks for: an ordinary `uses:` step (no
        # `run:` key at all) is normal, not a defect, and must not warn.
        root = tmp_path / "usesonly"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: pytest -q\n",
            encoding="utf-8",
        )
        result = cmd_ext.CommandsExtractor().extract(root, _opts(root))
        assert result.warnings == []

    def test_reader_crash_warns_with_a_human_label_not_a_function_name(self, repo, monkeypatch):
        # Finding 2: the blanket per-reader exception handler used to
        # render `could not read via _read_make: ...` -- a private
        # function name leaking into a user-visible KB warning, and (per
        # defect #3's signature) a whole reader's output silently gone
        # with no file named. Forces the defense-in-depth path directly
        # since none of the per-file guards can be tricked into raising.
        def _boom(root):
            raise RuntimeError("boom")

        monkeypatch.setattr(cmd_ext, "_read_make", _boom)
        result = cmd_ext.CommandsExtractor().extract(repo, _opts(repo))
        assert any("Makefile" in w and "boom" in w for w in result.warnings)
        assert not any("_read_make" in w for w in result.warnings)

    def test_ci_two_cd_lines_in_one_block_yield_no_directory_claim(self, tmp_path):
        # R34(a) (task review round 2): `cd web` then later `cd ../api`
        # in the same block -- the first `cd`'s target is NOT where the
        # later command actually runs. Claiming "web" here would be a
        # *wrong* directory, worse than the pre-Finding-1 silence this
        # whole mechanism exists to improve on. Silence is correct.
        root = tmp_path / "twocd"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n    steps:\n"
            "      - run: |\n"
            "          cd web\n"
            "          npm ci\n"
            "          cd ../api\n"
            "          npm test\n",
            encoding="utf-8",
        )
        s = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))["cmd.test"]
        assert "(in" not in s.l2_md
        assert "npm test" in s.l2_md.splitlines()[0]

    def test_ci_job_defaults_working_directory_is_used(self, tmp_path):
        # R34(b): jobs.<job>.defaults.run.working-directory is a common
        # monorepo idiom -- no step sets working-directory itself.
        root = tmp_path / "jobdefaults"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n"
            "    defaults:\n      run:\n        working-directory: web\n"
            "    steps:\n      - run: npm test\n",
            encoding="utf-8",
        )
        s = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))["cmd.test"]
        assert "(in web/)" in s.l2_md

    def test_ci_workflow_defaults_working_directory_is_used(self, tmp_path):
        # R34(b): a top-level defaults.run.working-directory, with no
        # job-level or step-level override at all.
        root = tmp_path / "workflowdefaults"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\ndefaults:\n  run:\n    working-directory: web\n"
            "jobs:\n  test:\n    steps:\n      - run: npm test\n",
            encoding="utf-8",
        )
        s = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))["cmd.test"]
        assert "(in web/)" in s.l2_md

    def test_ci_job_defaults_win_over_workflow_defaults(self, tmp_path):
        # R34(b) precedence, part 1: job default beats workflow default
        # when no step-level key is set. Deliberately does NOT set a
        # step-level working-directory -- a test that did would pass
        # regardless of whether this fallback tier works at all.
        root = tmp_path / "jobbeatswf"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\ndefaults:\n  run:\n    working-directory: wrong-wf-dir\n"
            "jobs:\n  test:\n"
            "    defaults:\n      run:\n        working-directory: web\n"
            "    steps:\n      - run: npm test\n",
            encoding="utf-8",
        )
        s = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))["cmd.test"]
        assert "(in web/)" in s.l2_md
        assert "wrong-wf-dir" not in s.l2_md

    def test_ci_step_working_directory_wins_over_job_and_workflow_defaults(self, tmp_path):
        # R34(b) precedence, part 2: a step's own working-directory beats
        # BOTH a job default and a workflow default set to something else.
        root = tmp_path / "stepbeatsall"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\ndefaults:\n  run:\n    working-directory: wrong-wf-dir\n"
            "jobs:\n  test:\n"
            "    defaults:\n      run:\n        working-directory: wrong-job-dir\n"
            "    steps:\n      - run: npm test\n        working-directory: web\n",
            encoding="utf-8",
        )
        s = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))["cmd.test"]
        assert "(in web/)" in s.l2_md
        assert "wrong-wf-dir" not in s.l2_md
        assert "wrong-job-dir" not in s.l2_md

    def test_ci_malformed_workflow_defaults_warns_instead_of_crashing(self, tmp_path):
        # R34(b) robustness: a malformed top-level `defaults:` (here a
        # list, not a mapping) must warn naming the file, never crash,
        # and must not silently swallow the rest of the workflow's output.
        root = tmp_path / "badwfdefaults"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\ndefaults: [oops]\n"
            "jobs:\n  test:\n    steps:\n      - run: npm test\n",
            encoding="utf-8",
        )
        result = cmd_ext.CommandsExtractor().extract(root, _opts(root))
        assert any("ci.yml" in w for w in result.warnings)
        s = _by_id(result)["cmd.test"]
        assert "(in" not in s.l2_md

    def test_ci_malformed_job_defaults_run_warns_instead_of_crashing(self, tmp_path):
        # R34(b) robustness, job scope: defaults.run is a bare string
        # instead of a mapping.
        root = tmp_path / "badjobdefaults"
        root.mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n"
            "    defaults:\n      run: oops\n"
            "    steps:\n      - run: npm test\n",
            encoding="utf-8",
        )
        result = cmd_ext.CommandsExtractor().extract(root, _opts(root))
        assert any("ci.yml" in w for w in result.warnings)
        s = _by_id(result)["cmd.test"]
        assert "(in" not in s.l2_md

    def test_command_embedding_a_credentialed_url_is_redacted(self, tmp_path):
        # Task review, Important 2: a captured command can itself carry a
        # URL with a plaintext credential (a health-check curl step, a
        # scripted git clone, ...) -- it must not reach l2_md, l3_md, or
        # summary verbatim.
        root = tmp_path / "cred-command"
        root.mkdir()
        (root / "package.json").write_text(
            '{"scripts": {"test": '
            '"curl https://admin:S3CR3TV4LUE@api.example.com/health && jest"}}\n',
            encoding="utf-8",
        )
        result = cmd_ext.CommandsExtractor().extract(root, _opts(root))
        s = _by_id(result)["cmd.test"]
        assert "S3CR3TV4LUE" not in s.l2_md
        assert "S3CR3TV4LUE" not in s.l3_md
        assert "S3CR3TV4LUE" not in s.summary
        assert "https://***@api.example.com/health" in s.l2_md

    # -- task review, Important 3: `_escape_pipe` only ever escaped a
    #    literal "|" -- an embedded newline breaks an L2 table just as
    #    surely, by starting a new row (or ending the table) mid-cell.

    def test_alternative_command_with_embedded_newline_does_not_break_the_l2_table(
        self, tmp_path
    ):
        root = tmp_path / "newline-command"
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  test:\n    steps:\n      - run: pytest -q\n",
            encoding="utf-8",
        )
        (root / "package.json").write_text(
            '{"scripts": {"test": "echo one\\necho two"}}',
            encoding="utf-8",
        )
        result = cmd_ext.CommandsExtractor().extract(root, _opts(root))
        s = _by_id(result)["cmd.test"]
        table_lines = [ln for ln in s.l2_md.splitlines() if ln.startswith("|")]
        # header + separator + exactly one alternative row -- an embedded
        # newline in the alternative's command must not turn one logical
        # row into extra lines that also start with "|".
        assert len(table_lines) == 3
        assert "echo one echo two" in table_lines[-1]


import sqlite3

from center_kb.codeingest.extractors import schema as schema_ext


class TestSchemaExtractor:
    def test_detects_migration_directories(self, repo, tmp_path):
        assert schema_ext.SchemaExtractor().detect(repo) is True
        empty = tmp_path / "empty4"
        empty.mkdir()
        assert schema_ext.SchemaExtractor().detect(empty) is False

    def test_one_section_per_table_from_sql_migrations(self, repo):
        sections = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))
        assert "db.restrictive_airspace" in sections
        assert sections["db.restrictive_airspace"].group == "db"

    def test_alter_table_add_column_accumulates(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "designation" in s.l2_md
        assert "effective_date" in s.l2_md      # added by V2, applied in filename order

    def test_column_order_is_preserved_not_sorted(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert s.l2_md.index("designation") < s.l2_md.index("airspace_type")

    def test_primary_key_is_recorded(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "PRIMARY KEY" in s.l3_md or "PK" in s.l2_md

    def test_primary_key_marks_the_correct_column_not_just_the_header(self, repo):
        # The brief's own test_primary_key_is_recorded is satisfied by the
        # literal "PK" in the L2 table *header* alone ("| Column | Type |
        # PK |"), regardless of whether PK detection does anything — it
        # would pass even with the detection logic deleted. This is the
        # stronger, falsifiable check: the *summary* names the detected PK
        # column by name, and only the "id" row (not "designation") is
        # actually marked in the PK column.
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "PK id" in s.summary
        id_row = next(ln for ln in s.l2_md.splitlines() if ln.strip().startswith("| id "))
        designation_row = next(
            ln for ln in s.l2_md.splitlines() if ln.strip().startswith("| designation ")
        )
        assert "yes" in id_row
        assert "yes" not in designation_row

    def test_l3_ddl_is_in_a_sql_fence_with_no_pipe_table(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "```sql" in s.l3_md
        assert "|" not in s.l3_md

    def test_prisma_schema_is_read(self, tmp_path):
        root = tmp_path / "prisma-repo"
        (root / "prisma").mkdir(parents=True)
        (root / "prisma" / "schema.prisma").write_text(
            "model Airspace {\n  id Int @id\n  designation String\n}\n", encoding="utf-8"
        )
        sections = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))
        assert "db.Airspace" in sections

    def test_explicit_db_flag_reads_sqlite(self, tmp_path):
        root = tmp_path / "sqlite-repo"
        root.mkdir()
        db = root / "app.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE roster (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        con.commit()
        con.close()
        result = schema_ext.SchemaExtractor().extract(
            root, _opts(root, db_paths=(db,))
        )
        sections = _by_id(result)
        assert "db.roster" in sections
        assert "name" in sections["db.roster"].l2_md

    def test_out_of_root_db_path_label_is_never_the_absolute_host_path(self, tmp_path):
        # Task review, Important 4: an out-of-root --db used to fall back
        # to path.as_posix() -- the fully-qualified host path, which
        # includes the OS user name on a typical developer machine and
        # made the same repo's output depend on *whose* machine ingested
        # it (spec Sec3.5's determinism guarantee). The label must be
        # stable and path-free instead.
        root = tmp_path / "repo"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        db = outside / "only.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE widgets (id INTEGER)")
        con.commit()
        con.close()
        result = schema_ext.SchemaExtractor().extract(root, _opts(root, db_paths=(db,)))
        s = _by_id(result)["db.widgets"]
        assert str(tmp_path) not in s.l2_md
        assert str(tmp_path) not in s.summary
        assert "--db:only.db" in s.l2_md
        assert "--db:only.db" in s.summary

    def test_stray_sqlite_file_is_never_read_without_the_flag(self, tmp_path):
        root = tmp_path / "stray"
        root.mkdir()
        con = sqlite3.connect(root / "fixture.db")
        con.execute("CREATE TABLE secret_fixture (id INTEGER)")
        con.commit()
        con.close()
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        assert all("secret_fixture" not in s.id for s in result.sections)

    def test_unsupported_ddl_warns_instead_of_guessing(self, tmp_path):
        root = tmp_path / "renames"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE a (id INT);\nALTER TABLE a RENAME TO b;\n", encoding="utf-8"
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        assert any("001.sql" in w for w in result.warnings)

    def test_tables_are_sorted_by_name(self, tmp_path):
        root = tmp_path / "two-tables"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE zulu (id INT);\nCREATE TABLE alpha (id INT);\n", encoding="utf-8"
        )
        ids = [s.id for s in schema_ext.SchemaExtractor().extract(root, _opts(root)).sections]
        assert ids == sorted(ids)

    # -- task review round 1 fixes -----------------------------------------

    def test_constraint_prefixed_column_names_are_not_dropped(self, tmp_path):
        # Important 1: a bare str.startswith("PRIMARY KEY"/...) match also
        # swallowed a real column merely *named* like a constraint keyword.
        root = tmp_path / "constraint-prefixed-columns"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n"
            "  unique_code TEXT,\n"
            "  check_digit INT,\n"
            "  constraint_name TEXT,\n"
            "  primary_email TEXT,\n"
            "  foreign_key_ref INT,\n"
            "  id INT PRIMARY KEY\n"
            ");\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        assert "6 columns" in s.summary
        for name in (
            "unique_code", "check_digit", "constraint_name",
            "primary_email", "foreign_key_ref",
        ):
            assert name in s.l2_md

    def test_primary_key_with_extra_internal_whitespace_is_not_a_fabricated_column(self, tmp_path):
        # Minor 8 (folded into Important 1's fix): "PRIMARY  KEY" (two
        # spaces) must still be recognised as the constraint, not parsed
        # as a bogus column named "PRIMARY".
        root = tmp_path / "pk-double-space"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  a INT,\n  b INT,\n  PRIMARY  KEY (a, b)\n);\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        assert "2 columns" in s.summary          # not 3 -- "PRIMARY" is not a fabricated column
        assert "(a, b)" in s.summary              # the PK constraint was still captured
        assert "| PRIMARY |" not in s.l2_md

    def test_line_comment_inside_create_table_does_not_fabricate_or_destroy_columns(self, tmp_path):
        # Important 2: an SQL line comment between two columns must not
        # fabricate a bogus "--" column, nor (via a keyword the comment's
        # own text happens to contain) swallow the real next column.
        root = tmp_path / "line-comment"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n"
            "  id INT, -- the id, unique\n"
            "  name TEXT\n"
            ");\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        assert "2 columns" in s.summary
        column_names = [
            ln.split("|")[1].strip()
            for ln in s.l2_md.splitlines()
            if ln.startswith("| ") and not ln.startswith("| ---") and not ln.startswith("| Column")
        ]
        assert column_names == ["id", "name"]

    def test_block_comment_inside_create_table_does_not_fabricate_a_column(self, tmp_path):
        # Important 2 (block-comment variant).
        root = tmp_path / "block-comment"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n"
            "  id INT,\n"
            "  /* note (a, b) */ name TEXT\n"
            ");\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        assert "2 columns" in s.summary
        assert "/*" not in s.l2_md
        column_names = [
            ln.split("|")[1].strip()
            for ln in s.l2_md.splitlines()
            if ln.startswith("| ") and not ln.startswith("| ---") and not ln.startswith("| Column")
        ]
        assert column_names == ["id", "name"]

    def test_quoted_identifier_with_a_comma_is_not_split_into_two_columns(self, tmp_path):
        # Minor 10: the splitter must not be string-literal-blind.
        root = tmp_path / "quoted-comma"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            'CREATE TABLE t (\n  "odd,name" TEXT,\n  id INT\n);\n', encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        assert "2 columns" in s.summary

    def test_unbalanced_paren_inside_a_string_literal_does_not_skew_column_splitting(self, tmp_path):
        # Minor 10 (unbalanced-paren-in-literal variant).
        root = tmp_path / "literal-paren"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  flag CHAR(1) DEFAULT ')',\n  other INT\n);\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        assert "2 columns" in s.summary
        assert "other" in s.l2_md

    def test_alter_table_add_constraint_is_not_recorded_as_a_column(self, tmp_path):
        # Important 3 / Ruling R35: ADD_COL_RE's optional "(?:COLUMN\s+)?"
        # also matches "ADD CONSTRAINT ...", which must not be recorded
        # as a column named "CONSTRAINT".
        root = tmp_path / "add-constraint"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text("CREATE TABLE t (id INT);\n", encoding="utf-8")
        (mig / "002.sql").write_text(
            "ALTER TABLE t ADD CONSTRAINT uq_t UNIQUE (id);\n", encoding="utf-8"
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "1 columns" in s.summary
        assert "CONSTRAINT" not in s.l2_md
        assert any("002.sql" in w for w in result.warnings)

    def test_re_create_table_if_not_exists_keeps_accumulated_alter_columns_and_warns(self, tmp_path):
        # Minor 4: a re-CREATE TABLE (typically IF NOT EXISTS re-asserting
        # a table a prior file already created) must not silently discard
        # columns an ALTER TABLE ADD COLUMN already accumulated.
        root = tmp_path / "recreate"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text("CREATE TABLE t (id INT);\n", encoding="utf-8")
        (mig / "002.sql").write_text("ALTER TABLE t ADD COLUMN x INT;\n", encoding="utf-8")
        (mig / "003.sql").write_text("CREATE TABLE IF NOT EXISTS t (id INT);\n", encoding="utf-8")
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "x" in s.l2_md
        assert "2 columns" in s.summary
        assert any("003.sql" in w for w in result.warnings)

    def test_trailing_unterminated_rename_still_warns(self, tmp_path):
        # Minor 6: a regression from adding _ALTER_STMT_RE -- a trailing
        # ALTER ... RENAME/DROP with no terminating ';' must still warn.
        root = tmp_path / "trailing-rename"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE a (id INT);\nALTER TABLE a RENAME TO b", encoding="utf-8"
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        assert any("001.sql" in w for w in result.warnings)

    def test_primary_key_marking_is_case_insensitive(self, tmp_path):
        # Minor 7: SQL identifiers are case-insensitive; PRIMARY KEY (ID)
        # must still mark a column declared "id".
        root = tmp_path / "case-pk"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  id INT,\n  other INT,\n  PRIMARY KEY (ID)\n);\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        id_row = next(ln for ln in s.l2_md.splitlines() if ln.strip().startswith("| id "))
        assert "yes" in id_row

    def test_sqlite_uri_percent_encodes_uri_special_characters(self, tmp_path):
        # Minor 9: %, #, ? and & in the path must never be read as URI
        # syntax that could smuggle in a second, path-controlled query
        # string ahead of our own "?mode=ro".
        tricky = tmp_path / "weird&name%tag#x?mode=rwc.db"
        uri = schema_ext._sqlite_uri(tricky, "ro")
        query_start = uri.rindex("?mode=ro")
        assert "?" not in uri[:query_start]
        assert "&" not in uri[:query_start]

    def test_crafted_filename_cannot_relax_the_read_only_connection(self, tmp_path):
        # Minor 9 (end-to-end): a filename containing URI-special
        # characters (Windows-legal ones only: '?' is not) must not
        # weaken the mode=ro guarantee, and the reader must still work.
        root = tmp_path / "crafted-name"
        root.mkdir()
        db = root / "weird&name%tag#x.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE roster (id INTEGER PRIMARY KEY, name TEXT)")
        con.commit()
        con.close()

        result = schema_ext.SchemaExtractor().extract(root, _opts(root, db_paths=(db,)))
        sections = _by_id(result)
        assert "db.roster" in sections

        check = sqlite3.connect(schema_ext._sqlite_uri(db, "ro"), uri=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                check.execute("INSERT INTO roster (id, name) VALUES (99, 'x')")
        finally:
            check.close()

    def test_alembic_column_types_are_captured_whole_and_primary_key_is_seen(self, tmp_path):
        # Reviewer G-13: `[^,)]+` stopped at the first paren, rendering
        # `sa.Integer(` and missing `primary_key=True`. Round 2's concern —
        # never fabricate `sa.Numeric(10)` from `sa.Numeric(10, 2)` — holds
        # because the type is now the first top-level argument, parens
        # balanced, not a truncated capture with a paren appended.
        root = tmp_path / "alembic-types"
        versions = root / "versions"
        versions.mkdir(parents=True)
        (versions / "0001_x.py").write_text(
            "def upgrade():\n"
            "    op.create_table(\n"
            "        'widgets',\n"
            "        sa.Column('id', sa.Integer(), primary_key=True),\n"
            "        sa.Column('amt', sa.Numeric(10, 2), nullable=False),\n"
            "        sa.Column('meta', sa.JSON(none_as_null=True)),\n"
            "    )\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.widgets"]
        assert "| id | sa.Integer() | yes |" in s.l2_md
        assert "| amt | sa.Numeric(10, 2) |  |" in s.l2_md
        assert "| meta | sa.JSON(none_as_null=True) |  |" in s.l2_md
        assert "PK id" in s.summary

    def test_alembic_column_truncated_at_end_of_file_stays_visibly_incomplete(self, tmp_path):
        # Reviewer G-13 round 2: _matching_close_paren returns an index AT
        # the last real character (not past it) when a call never closes.
        # The old exclusive slice `scope[cm.end():call_close]` dropped that
        # character, turning a visibly truncated `sa.Integer(` into a
        # plausible-looking, complete (and wrong) `sa.Integer`.
        root = tmp_path / "alembic-truncated"
        versions = root / "versions"
        versions.mkdir(parents=True)
        (versions / "0001_x.py").write_text(
            "def upgrade():\n"
            "    op.create_table(\n"
            "        'widgets',\n"
            "        sa.Column('id', sa.Integer(",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.widgets"]
        assert "| id | sa.Integer( |  |" in s.l2_md
        assert "sa.Integer()" not in s.l2_md

    def test_alembic_composite_primary_key_is_not_reduced_to_its_first_column(self, tmp_path):
        # Reviewer G-13 round 2 (plan-overriding ruling): `if not pk`
        # stopped at the first `primary_key=True`, so a 2-column composite
        # PK rendered as PK on only the first column and left the second's
        # PK cell blank -- a confident false statement. Composite PKs are
        # ordinary in Alembic; the full clause must reach the document.
        root = tmp_path / "alembic-composite-pk"
        versions = root / "versions"
        versions.mkdir(parents=True)
        (versions / "0001_x.py").write_text(
            "def upgrade():\n"
            "    op.create_table(\n"
            "        'membership',\n"
            "        sa.Column('team_id', sa.Integer(), primary_key=True),\n"
            "        sa.Column('user_id', sa.Integer(), primary_key=True),\n"
            "    )\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.membership"]
        assert "| team_id | sa.Integer() | yes |" in s.l2_md
        assert "| user_id | sa.Integer() | yes |" in s.l2_md
        assert "PK PRIMARY KEY (team_id, user_id)" in s.summary

    def test_clean_type_does_not_fabricate_a_closing_paren_for_a_literal(self, tmp_path):
        # New Minor: a literal like DEFAULT '(' has a genuinely unbalanced
        # paren count, but it is not a truncated capture -- it is exactly
        # what the source says. Appending ')' fabricates text that was
        # never in the DDL.
        root = tmp_path / "literal-open-paren"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  flag CHAR(1) DEFAULT '(',\n  id INT\n);\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        assert "CHAR(1) DEFAULT '('" in s.l2_md
        assert "CHAR(1) DEFAULT '(')" not in s.l2_md

    def test_a_parse_time_crash_on_one_file_does_not_discard_other_files_tables(self, tmp_path, monkeypatch):
        # Minor 5: a parse-time exception on one migration file must not
        # unwind past the per-file loop and discard every other file's
        # already-accumulated tables (the defect class this stage has
        # shipped twice already). No concrete natural trigger exists, so
        # this simulates one by making CREATE_RE itself raise for a
        # specific file's text.
        root = tmp_path / "crash-one-file"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text("CREATE TABLE good_one (id INT);\n", encoding="utf-8")
        (mig / "002.sql").write_text("CREATE TABLE boom (id INT);\n", encoding="utf-8")

        real_create_re = schema_ext.CREATE_RE

        class _Boom:
            def finditer(self, text):
                if "boom" in text:
                    raise RuntimeError("simulated parser crash")
                return real_create_re.finditer(text)

        monkeypatch.setattr(schema_ext, "CREATE_RE", _Boom())
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        ids = [s.id for s in result.sections]
        assert "db.good_one" in ids
        assert any("002.sql" in w for w in result.warnings)

    # -- task review round 2 fixes (Ruling R36) ------------------------------

    def test_backslash_escaped_quote_does_not_delete_subsequent_columns(self, tmp_path):
        # New Important, part 1: round 1's quote tracker ignored
        # backslash escapes entirely. 'it\'s' was read as closing at the
        # escaped quote, then re-opening a literal that ran to the end
        # of the body, silently swallowing every column after it.
        root = tmp_path / "backslash-escape"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n"
            "  a VARCHAR(10) DEFAULT 'it\\'s',\n"
            "  b INT,\n"
            "  c INT\n"
            ");\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "3 columns" in s.summary
        assert "b" in s.l2_md and "c" in s.l2_md
        assert not any("could not reliably" in w for w in result.warnings)

    def test_backtick_quoted_identifier_with_comment_chars_does_not_delete_a_column(self, tmp_path):
        # New Important, part 1 (backtick variant): round 1's comment
        # stripper and splitter tracked only '/" -- a "--" inside a
        # backtick-quoted identifier was misread as a real line comment,
        # deleting everything after it on that line.
        root = tmp_path / "backtick-comment-chars"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  `a--b` INT,\n  keepme TEXT\n);\n", encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "2 columns" in s.summary
        assert "keepme" in s.l2_md

    def test_bracket_quoted_identifier_with_comment_chars_does_not_delete_a_column(self, tmp_path):
        # New Important, part 1 (bracket variant, T-SQL style).
        root = tmp_path / "bracket-comment-chars"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  [a--b] INT,\n  keepme TEXT\n);\n", encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "2 columns" in s.summary
        assert "keepme" in s.l2_md

    def test_unterminated_string_literal_triggers_the_desync_guard_not_silent_deletion(self, tmp_path):
        # New Important, part 2 (Ruling R36's desync guard): a literal
        # that never closes before end of body must not silently
        # swallow the rest of the columns -- it must warn, naming the
        # file, and fall back to a split that at least keeps every
        # column visible (even if one column's type text looks odd).
        root = tmp_path / "desync-guard"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n"
            "  a INT,\n"
            "  note TEXT DEFAULT 'oops,\n"
            "  b INT\n"
            ");\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        # "b" as a bare substring would also appear merged into "note"'s
        # type text (e.g. "TEXT DEFAULT 'oops, b INT") if the guard did
        # nothing -- that would be silent deletion of "b" as a *column*
        # while still passing a substring check, so assert the stronger,
        # falsifiable property: "b" is its own row, and the column count
        # matches the quote-blind fallback's (correct, if odd-looking)
        # 3-way split.
        assert "3 columns" in s.summary
        assert any(ln.strip().startswith("| b ") for ln in s.l2_md.splitlines())
        assert any("001.sql" in w for w in result.warnings)

    def test_nested_block_comment_does_not_fabricate_or_destroy_columns(self, tmp_path):
        # Residual half of Important 2's class: nested block comments
        # are legal PostgreSQL; a non-nesting */-search stops at the
        # *first* */ (the inner one), leaving " still outer */ b INT" to
        # be mis-parsed as a fabricated column with "b" swallowed into
        # its type text.
        root = tmp_path / "nested-block-comment"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n"
            "  a INT,\n"
            "  /* outer /* inner */ still outer */ b INT\n"
            ");\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.t"]
        # task review round 3: "'2 columns' in summary" and "'b' in
        # l2_md" both hold even against the *defect* -- reverting to a
        # non-nesting search stops at the inner "*/", leaving " still
        # outer */ b INT" to be mis-parsed as one fabricated column
        # named "still" whose type text is "outer */ b INT" (2 columns
        # total: "a" and "still"; "b" survives only as a substring of
        # that merged type). Assert the row set instead.
        assert "2 columns" in s.summary
        column_names = [
            ln.split("|")[1].strip()
            for ln in s.l2_md.splitlines()
            if ln.startswith("| ") and not ln.startswith("| ---") and not ln.startswith("| Column")
        ]
        assert column_names == ["a", "b"]

    def test_scan_sql_flags_desync_on_unterminated_literal(self):
        result = schema_ext._scan_sql("a INT, b TEXT DEFAULT 'unterminated", backslash_escapes=True)
        assert result.desynced is True

    def test_scan_sql_does_not_desync_on_backslash_escaped_quote(self):
        result = schema_ext._scan_sql("a TEXT DEFAULT 'it\\'s', b INT", backslash_escapes=True)
        assert result.desynced is False

    def test_scan_sql_tracks_backtick_and_bracket_quoting(self):
        result = schema_ext._scan_sql("`a--b` INT, [c--d] TEXT", backslash_escapes=True)
        assert result.desynced is False
        kinds = [kind for kind, _ in result.segments]
        assert "backtick" in kinds
        assert "bracket" in kinds

    def test_tail_unsupported_ddl_warning_does_not_dump_the_whole_file(self, tmp_path):
        # New Minor: when no ALTER in the file ever terminates with ';',
        # last_end stays 0 and the naive "warn with the whole tail"
        # approach dumps the entire (potentially huge) file text into
        # one warning string.
        root = tmp_path / "trailing-rename-long"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        padding = "\n" * 200
        (mig / "001.sql").write_text(
            f"CREATE TABLE a (id INT);\n{padding}ALTER TABLE a RENAME TO b",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        matches = [w for w in result.warnings if "001.sql" in w and "RENAME" in w]
        assert matches
        assert len(matches[0]) < 100

    # -- task review round 3 fixes (Ruling R38 + [-tracking) ------------------

    def test_standard_sql_backslash_literal_gives_three_columns_with_ambiguity_warning(
        self, tmp_path
    ):
        # Ruling R38 repro 1 (standard SQL): '\' is an ordinary character
        # in SQLite/Postgres(standard_conforming_strings=on)/MSSQL/Oracle.
        # Round 2's escape-always-on tracker misread '\' as escaping the
        # closing quote, then falsely re-closed on the apostrophe in the
        # comment's "user's", silently merging every column after "esc"
        # into one row with zero warnings. The dual-scan guard must
        # detect the disagreement, prefer the (correct) literal reading,
        # and warn that the dialect was ambiguous.
        root = tmp_path / "standard-sql-backslash"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n"
            "  esc CHAR(1) DEFAULT '\\',\n"
            "  name TEXT, -- the user's display name\n"
            "  email TEXT\n"
            ");\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "3 columns" in s.summary
        column_names = [
            ln.split("|")[1].strip()
            for ln in s.l2_md.splitlines()
            if ln.startswith("| ") and not ln.startswith("| ---") and not ln.startswith("| Column")
        ]
        assert column_names == ["esc", "name", "email"]
        assert any("ambiguous" in w and "001.sql" in w for w in result.warnings)

    def test_resolve_scan_branch_both_desync_returns_none(self):
        # Branch: neither backslash reading can find a close at all.
        resolution = schema_ext._resolve_scan("a INT, b TEXT DEFAULT 'unterminated")
        assert resolution.segments is None
        assert resolution.ambiguous is False

    def test_resolve_scan_branch_only_escape_reading_clean_mysql_wins_no_warning(self):
        # Branch: 'it\'s' -- the escape reading closes correctly right
        # after the real closing quote; the literal reading re-opens on
        # the "s'" and runs off the end of the text with no more quotes
        # to close on.
        resolution = schema_ext._resolve_scan("a TEXT DEFAULT 'it\\'s', b INT")
        assert resolution.segments is not None
        assert resolution.ambiguous is False
        joined = "".join(seg for _, seg in resolution.segments)
        assert joined == "a TEXT DEFAULT 'it\\'s', b INT"
        quote_segments = [seg for kind, seg in resolution.segments if kind == "squote"]
        assert quote_segments == ["'it\\'s'"]

    def test_resolve_scan_branch_only_literal_reading_clean_standard_sql_wins_no_warning(self):
        # Branch (mirror of the above): a lone backslash literal with no
        # other quote characters anywhere else in the text for the
        # escape reading to falsely re-close on -- it just runs off the
        # end, while the literal reading closes immediately and cleanly.
        resolution = schema_ext._resolve_scan("a TEXT DEFAULT '\\', b INT, c INT")
        assert resolution.segments is not None
        assert resolution.ambiguous is False
        quote_segments = [seg for kind, seg in resolution.segments if kind == "squote"]
        assert quote_segments == ["'\\'"]

    def test_resolve_scan_branch_both_clean_and_agree_no_backslash_present(self):
        # Branch: no backslash anywhere, so both readings are byte-for-
        # byte identical -- the common case for the vast majority of DDL.
        resolution = schema_ext._resolve_scan("a INT, b TEXT")
        assert resolution.segments is not None
        assert resolution.ambiguous is False

    def test_resolve_scan_branch_both_clean_and_disagree_takes_literal_reading_with_flag(self):
        # Branch: both readings find *a* close, but at different points
        # -- the escape reading swallows through to a later, unrelated
        # apostrophe in an English comment; the literal reading closes
        # right after the lone backslash. `ambiguous` must be True and
        # the literal (standard-SQL) reading must be the one returned.
        body = "esc CHAR(1) DEFAULT '\\', name TEXT, -- the user's name\n email TEXT"
        resolution = schema_ext._resolve_scan(body)
        assert resolution.segments is not None
        assert resolution.ambiguous is True
        joined = "".join(seg for _, seg in resolution.segments)
        assert joined == body
        quote_segments = [seg for kind, seg in resolution.segments if kind == "squote"]
        assert quote_segments == ["'\\'"]

    def test_unbalanced_bracket_in_check_constraint_does_not_silently_merge_columns(
        self, tmp_path
    ):
        # New [-tracking defect: an unbalanced '[' inside a CHECK
        # expression finds some later, unrelated ']' and swallows every
        # comma and ')' in between, merging what should be 3 columns
        # into 1 with no warning. The bracket-local-paren-depth guard
        # must treat this as a desync and fall back to the quote-blind
        # split, which correctly returns 3.
        root = tmp_path / "bracket-check"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (a INT CHECK (a > [1), b INT, c INT]);\n", encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "3 columns" in s.summary
        column_names = [
            ln.split("|")[1].strip()
            for ln in s.l2_md.splitlines()
            if ln.startswith("| ") and not ln.startswith("| ---") and not ln.startswith("| Column")
        ]
        assert column_names == ["a", "b", "c"]
        assert any("001.sql" in w for w in result.warnings)

    def test_tsql_bracket_identifiers_still_parse_correctly(self, tmp_path):
        # Must not break: valid T-SQL bracket-quoted identifiers.
        root = tmp_path / "tsql-brackets"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t ([Id] [int] IDENTITY(1,1), name TEXT);\n", encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "2 columns" in s.summary
        assert not result.warnings

    def test_postgres_array_suffix_brackets_still_parse_correctly(self, tmp_path):
        # Must not break: Postgres array-type suffixes (empty brackets).
        root = tmp_path / "pg-array"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (tags TEXT[], grid INT[][]);\n", encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "2 columns" in s.summary
        assert not result.warnings

    def test_doubled_bracket_escape_in_identifier_still_parses_correctly(self, tmp_path):
        # Must not break: a doubled ']]' escapes a literal ']' inside a
        # bracket-quoted identifier.
        root = tmp_path / "bracket-escaped"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t ([we]]ird] INT, id INT);\n", encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "2 columns" in s.summary
        assert not result.warnings

    def test_double_bracket_still_warns_rather_than_crashing(self, tmp_path):
        # Must not break (or rather: must still degrade the same way):
        # "[[VERSION]]" is pathological enough to desync -- that's an
        # accepted "warn" outcome (never silent), not a regression.
        root = tmp_path / "bracket-double"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t ([[VERSION]] INT, id INT);\n", encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.t"]
        assert "2 columns" in s.summary
        assert any("001.sql" in w for w in result.warnings)

    def test_desync_fallback_warning_states_fabrication_risk_plainly(self, tmp_path):
        # An unmatched '[' anywhere in the file desyncs _strip_sql_comments,
        # whose fallback returns the file entirely unstripped -- a
        # commented-out CREATE TABLE then parses as a real, phantom
        # table. The warning must say plainly that a table or column may
        # be fabricated, not just "comments unstripped" (task review
        # round 3).
        root = tmp_path / "ghost-table"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (a INT CHECK (a > [1), b INT, c INT]);\n"
            "/* CREATE TABLE ghost (x INT); */\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        assert any("FABRICATED" in w for w in result.warnings)

    # -- task review, Critical 1: CREATE_RE's body scan ran to the first
    #    literal "');'" anywhere in the rest of the *file*, not to the
    #    table's own closing paren, so a dialect trailing clause between
    #    ")" and ";" smeared one table's tail into another's columns and
    #    silently deleted the next table outright. --------------------

    def test_mysql_engine_clause_does_not_delete_the_next_table(self, tmp_path):
        # The exact reported failure: two MySQL tables, each closed with
        # ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;" rather than a bare
        # ");". Before the fix, CREATE_RE's non-greedy body scan never
        # finds a literal "');'" adjacency anywhere in this file at all
        # (neither table's close is immediately followed by ";"), so it
        # matches nothing: both tables vanish with zero warnings.
        root = tmp_path / "mysql-engine"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE `orders` (\n"
            "  id INT NOT NULL,\n"
            "  total DECIMAL(10,2)\n"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
            "CREATE TABLE `customers` (\n"
            "  id INT NOT NULL,\n"
            "  email VARCHAR(255)\n"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        sections = _by_id(result)
        assert "db.orders" in sections
        assert "db.customers" in sections
        orders = sections["db.orders"]
        assert "2 columns" in orders.summary
        assert "ENGINE" not in orders.l2_md
        assert "customers" not in orders.l2_md
        customers = sections["db.customers"]
        assert "2 columns" in customers.summary
        assert "email" in customers.l2_md
        assert not result.warnings

    def test_sqlite_without_rowid_clause_terminates_the_table(self, tmp_path):
        root = tmp_path / "sqlite-without-rowid"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  id INT,\n  name TEXT\n) WITHOUT ROWID;\n"
            "CREATE TABLE u (id INT);\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        sections = _by_id(result)
        assert "db.t" in sections
        assert "db.u" in sections
        assert "2 columns" in sections["db.t"].summary
        assert "ROWID" not in sections["db.t"].l2_md
        assert not result.warnings

    def test_postgres_partition_by_clause_terminates_the_table(self, tmp_path):
        # The trailing clause's own parens ("RANGE (id)") must not be
        # mistaken for more of the table body once the table's real
        # closing paren has already been found.
        root = tmp_path / "pg-partition"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  id INT,\n  ts TIMESTAMP\n) PARTITION BY RANGE (id);\n"
            "CREATE TABLE u (id INT);\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        sections = _by_id(result)
        assert "db.t" in sections
        assert "db.u" in sections
        assert "2 columns" in sections["db.t"].summary
        assert "PARTITION" not in sections["db.t"].l2_md
        assert not result.warnings

    def test_final_create_table_with_no_trailing_semicolon_still_parses(self, tmp_path):
        root = tmp_path / "no-trailing-semicolon"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE t (\n  id INT,\n  name TEXT\n)",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        sections = _by_id(result)
        assert "db.t" in sections
        assert "2 columns" in sections["db.t"].summary

    def test_standard_sql_two_table_file_is_unaffected(self, tmp_path):
        # Confirms the ordinary, already-working shape -- two tables each
        # terminated with a plain ");" -- is unchanged by bounding the
        # body scan with _matching_close_paren instead of the old literal
        # "');'" search.
        root = tmp_path / "standard-sql"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE orders (\n  id INT,\n  total DECIMAL(10,2)\n);\n"
            "CREATE TABLE customers (\n  id INT,\n  email TEXT\n);\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        sections = _by_id(result)
        assert "db.orders" in sections
        assert "db.customers" in sections
        assert "2 columns" in sections["db.orders"].summary
        assert "2 columns" in sections["db.customers"].summary
        assert not result.warnings

    def test_create_table_name_create_re_cannot_match_is_warned_not_silently_skipped(
        self, tmp_path
    ):
        # Critical 1 part 2: a CREATE TABLE occurrence CREATE_RE's name
        # group cannot match (a leading digit is not a valid identifier
        # start) must not disappear without a trace -- warn naming the
        # file, per spec Sec3.9, rather than a guess.
        root = tmp_path / "unmatched-name"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE 1abc (id INT);\nCREATE TABLE good (id INT);\n",
            encoding="utf-8",
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        sections = _by_id(result)
        assert "db.good" in sections
        assert any("001.sql" in w and "CREATE TABLE" in w for w in result.warnings)

    def _two_dir_users(self, tmp_path):
        root = tmp_path / "twodirs"
        billing = root / "services" / "billing" / "migrations"
        flyway = root / "src" / "main" / "resources" / "db" / "migration"
        billing.mkdir(parents=True)
        flyway.mkdir(parents=True)
        (billing / "001_init.sql").write_text(
            "CREATE TABLE users (\n  id BIGINT NOT NULL,\n  plan VARCHAR(32) NOT NULL\n);\n",
            encoding="utf-8",
        )
        (flyway / "V1__init.sql").write_text(
            "CREATE TABLE users (\n  id BIGINT NOT NULL,\n  email VARCHAR(255) NOT NULL,\n"
            "  created_at DATETIME NOT NULL,\n  PRIMARY KEY (id)\n);\n",
            encoding="utf-8",
        )
        (flyway / "V2__alter.sql").write_text(
            "ALTER TABLE users ADD COLUMN last_login DATETIME NULL;\n", encoding="utf-8"
        )
        return root

    def test_duplicate_table_in_another_directory_is_not_merged(self, tmp_path):
        # Reviewer G-4: `plan` + `last_login` were joined into a users table
        # that exists in neither schema.
        root = self._two_dir_users(tmp_path)
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.users"]
        assert "| plan |" in s.l2_md
        assert "email" not in s.l2_md
        assert "last_login" not in s.l2_md
        assert "Table users: 2 columns" in s.summary
        assert any(
            "duplicate CREATE TABLE 'users' in src/main/resources/db/migration/V1__init.sql" in w
            and "keeping the definition from services/billing/migrations/001_init.sql" in w
            and "not merged" in w
            for w in result.warnings
        )

    def test_alter_from_another_directory_is_not_applied_and_warns(self, tmp_path):
        root = self._two_dir_users(tmp_path)
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.users"]
        assert "V2__alter.sql" not in s.l2_md          # not in Source either
        assert any(
            "ALTER TABLE 'users' ADD COLUMN in src/main/resources/db/migration/V2__alter.sql not applied"
            in w and "created in services/billing/migrations/001_init.sql" in w
            for w in result.warnings
        )

    def test_alter_in_the_same_directory_still_applies(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "| effective_date |" in s.l2_md

    def test_ef_table_says_columns_not_extracted_instead_of_an_empty_table(self, tmp_path):
        # Reviewer G-13: a header row with no rows and "0 columns" reads as
        # "this table has no columns".
        root = tmp_path / "efrepo"
        mig = root / "Migrations"
        mig.mkdir(parents=True)
        (mig / "20240101_Init.cs").write_text(
            'migrationBuilder.CreateTable(\n    name: "Invoices",\n    columns: table => new {}\n);\n',
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.Invoices"]
        assert "| Column | Type | PK |" not in s.l2_md
        assert "_Columns not extracted: EF Core migrations are recognised by table name only._" in s.l2_md
        assert "_Source: Migrations/20240101_Init.cs_" in s.l2_md
        assert "Table Invoices: columns not extracted (EF migration), PK none detected" in s.summary

    def test_created_in_empty_string_never_matches_a_root_level_created_in(self):
        # Carried from Task 7's review: _dirname("") returns "." same as a
        # root-level migration file's _dirname. After this task all five
        # TableRecord construction sites set created_in, so an unset value
        # is not actually reachable today -- this guard is defensive
        # against a future reader that forgets to set the field, ensuring
        # that "created_in was never set" could never be silently treated
        # as "created at the repo root" by the _dirname guards in
        # _apply_sql_file. Cheap to keep, pinned directly against _dirname.
        assert schema_ext._dirname("") != schema_ext._dirname("root_level.sql")


class TestIntegrationsExtractor:
    def test_detects_env_example_or_openapi_servers(self, repo, tmp_path):
        assert int_ext.IntegrationsExtractor().detect(repo) is True
        empty = tmp_path / "empty5"
        empty.mkdir()
        assert int_ext.IntegrationsExtractor().detect(empty) is False

    def test_groups_keys_into_named_integrations(self, repo):
        sections = _by_id(int_ext.IntegrationsExtractor().extract(repo, _opts(repo)))
        assert "int.kafka" in sections
        assert "int.s3" in sections
        for s in sections.values():
            assert s.group == "integrations"
            assert s.summary

    def test_never_emits_a_value(self, repo):
        result = int_ext.IntegrationsExtractor().extract(repo, _opts(repo))
        # Minor review finding: `summary` is the field that reaches
        # `_manifest.yaml` (core.run() writes every section's `summary`
        # into it) -- checking only l2_md/l3_md would miss a leak that
        # only shows up in the rendered summary sentence.
        blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
        for secret in ("do-not-ship-this-value", "localhost:9092",
                       "airspace-assets", "postgres://localhost/airspace"):
            assert secret not in blob

    def test_never_emits_compose_environment_values(self, repo):
        # Extra coverage: the brief's own test above only checks
        # .env.example's *values* -- it never checks the fixture's
        # docker-compose.yml, whose `environment:` block declares
        # DIFFERENT values ("postgres://db/airspace", "kafka:9092") for
        # the very same two keys. A leak specific to the compose reader
        # would pass the brief's verbatim test untouched.
        result = int_ext.IntegrationsExtractor().extract(repo, _opts(repo))
        blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
        assert "postgres://db/airspace" not in blob
        assert "kafka:9092" not in blob

    def test_never_reads_a_real_dotenv(self, tmp_path):
        root = tmp_path / "real-env"
        root.mkdir()
        (root / ".env").write_text("REAL_SECRET_TOKEN=abc123\n", encoding="utf-8")
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
        assert "REAL_SECRET_TOKEN" not in blob
        assert "abc123" not in blob

    def test_l3_has_no_pipe_table(self, repo):
        for s in int_ext.IntegrationsExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    # --- extra coverage: closes the vacuous-test gap in the brief's own
    # detect() test above, which never isolates "env only" from "openapi
    # servers only" (both are true in `repo` at once) -- and enumerates,
    # per-path, every route a string can take into the rendered output of
    # a compose `environment:` block (task B4's postmortem: two rounds of
    # "fix the reported branch" each patched one branch of a multi-branch
    # helper while the others stayed vulnerable). Each test below asserts
    # on rendered l2_md/l3_md, never on a helper's return value.

    def test_detects_from_env_file_alone(self, tmp_path):
        root = tmp_path / "env-only"
        root.mkdir()
        (root / ".env.example").write_text("KAFKA_BROKER_URL=x\n", encoding="utf-8")
        assert int_ext.IntegrationsExtractor().detect(root) is True

    def test_detects_from_openapi_servers_alone(self, tmp_path):
        root = tmp_path / "openapi-only"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\nservers:\n  - url: https://api.example.com\npaths: {}\n",
            encoding="utf-8",
        )
        assert int_ext.IntegrationsExtractor().detect(root) is True

    def test_does_not_detect_openapi_with_no_servers(self, tmp_path):
        root = tmp_path / "openapi-no-servers"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\npaths: {}\n", encoding="utf-8",
        )
        assert int_ext.IntegrationsExtractor().detect(root) is False

    def test_compose_environment_mapping_form_never_leaks_value(self, tmp_path):
        # Path 1: environment: {KEY: value} -- a top-level mapping.
        root = tmp_path / "compose-mapping"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: web:1\n"
            "    environment:\n"
            "      KAFKA_BROKER_URL: super-secret-broker-value\n",
            encoding="utf-8",
        )
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        blob = "".join(s.l2_md + s.l3_md for s in result.sections)
        assert "KAFKA_BROKER_URL" in blob
        assert "super-secret-broker-value" not in blob

    def test_compose_environment_list_string_form_never_leaks_value(self, tmp_path):
        # Path 2: environment: ["KEY=value"] -- a list of plain strings.
        root = tmp_path / "compose-list-string"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: web:1\n"
            "    environment:\n"
            '      - "KAFKA_BROKER_URL=super-secret-broker-value"\n',
            encoding="utf-8",
        )
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        blob = "".join(s.l2_md + s.l3_md for s in result.sections)
        assert "KAFKA_BROKER_URL" in blob
        assert "super-secret-broker-value" not in blob

    def test_compose_environment_list_single_pair_mapping_form_never_leaks_value(self, tmp_path):
        # Path 3: a `KEY=value` list entry whose own text contains ": ",
        # so YAML parses that one list item as a single-pair mapping
        # instead of a plain string -- the exact shape of task B4's
        # Critical secret leak (a naive str(item) published key AND
        # value). Here the mapping's raw key is "KAFKA_BROKER_URL=kafka"
        # and its value is the int 9092 -- neither "kafka" the hostname
        # fragment nor 9092 the port may ever reach rendered output.
        root = tmp_path / "compose-list-dict"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: web:1\n"
            "    environment:\n"
            "      - KAFKA_BROKER_URL=kafka: 9092\n",
            encoding="utf-8",
        )
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        blob = "".join(s.l2_md + s.l3_md for s in result.sections)
        assert "KAFKA_BROKER_URL" in blob
        assert "9092" not in blob
        assert "kafka:" not in blob.lower().replace("kafka_broker_url", "")

    # --- Critical (Ruling R40): a compose `environment:` entry that
    # carries no "=" at all -- so the old sanitiser's "split on the
    # first =" was a no-op -- used to publish the *entire* polluted
    # string, credentials included, whenever it happened to `startswith`
    # one of the INTEGRATION_PREFIXES. Each test below asserts on
    # rendered l2_md, l3_md, AND summary (summary is what reaches
    # `_manifest.yaml` via core.run()).

    def test_colon_delimited_list_string_entry_does_not_leak_its_value(self, tmp_path):
        # `- REDIS_URL:redis://user:hunter2@cache` has no "=" anywhere;
        # it stays a plain YAML string (no ": " substring to trigger a
        # nested-mapping reading) and starts with the "REDIS" prefix.
        root = tmp_path / "colon-list-string"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  cache:\n"
            "    image: redis:7\n"
            "    environment:\n"
            "      - REDIS_URL:redis://user:hunter2@cache\n",
            encoding="utf-8",
        )
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
        assert "hunter2" not in blob
        assert result.sections == []  # nothing survives sanitisation -> no int.redis at all

    def test_colon_containing_mapping_key_does_not_leak_its_value(self, tmp_path):
        # A block-mapping `environment:` entry whose *key* (not value)
        # contains a colon: YAML takes everything up to the LAST ": " as
        # the key, so the parsed key is the literal string
        # "REDIS_URL:redis://:hunter2@cache" and the value is the int
        # 6379 -- never read by any branch of `env_keys_from`, but the
        # (old, buggy) *key* text alone already carried the credential.
        root = tmp_path / "colon-mapping-key"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  cache:\n"
            "    image: redis:7\n"
            "    environment:\n"
            "      REDIS_URL:redis://:hunter2@cache: 6379\n",
            encoding="utf-8",
        )
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
        assert "hunter2" not in blob
        assert "6379" not in blob
        assert result.sections == []

    def test_quoted_colon_delimited_list_entry_does_not_leak_its_value(self, tmp_path):
        # Quoting forces YAML to keep this as one literal string (never
        # a nested mapping) even though it contains ": " -- reproduces
        # the reviewer's third confirmed shape.
        root = tmp_path / "colon-quoted-list"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  broker:\n"
            "    image: kafka:3\n"
            "    environment:\n"
            '      - "KAFKA_BROKER_URL: quoted-secret-value"\n',
            encoding="utf-8",
        )
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        blob = "".join(s.l2_md + s.l3_md + s.summary for s in result.sections)
        assert "quoted-secret-value" not in blob
        assert result.sections == []

    def test_compose_environment_scalar_shape_warns(self, tmp_path):
        # Minor review finding: every other wrong shape in this reader
        # (top-level, services, one service) warns naming the file; a
        # scalar `environment:` (e.g. a bare "KEY=value" string instead
        # of a mapping or list) was the one silent exception.
        root = tmp_path / "compose-scalar-env"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: web:1\n"
            "    environment: KAFKA_BROKER_URL=secret\n",
            encoding="utf-8",
        )
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        assert any("docker-compose.yml" in w for w in result.warnings)
        assert result.sections == []

    def test_dotted_and_hyphenated_env_keys_are_kept(self, tmp_path):
        # Ruling R41 (round 2 of the R40 fix): the first widened rule
        # was still too narrow -- a bare identifier only, which silently
        # dropped a dotted key that matches an INTEGRATION_PREFIXES
        # prefix, and a hyphenated key that matches a generic suffix,
        # with no warning. `_KEY_TOKEN_RE` now also accepts `.` and `-`.
        # (The reviewer's own literal reproduction keys --
        # `cluster.name`, `discovery.type`, `xpack.security.enabled` --
        # never classify into any `int.*` group at all, matching no
        # prefix or suffix, so they aren't usable for an *observable*
        # assertion here; this test picks dotted/hyphenated keys that
        # both survive sanitisation AND classify, so the property is
        # actually visible in rendered output.)
        root = tmp_path / "int-dotted-hyphenated"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  search:\n"
            "    image: redis:7\n"
            "    environment:\n"
            "      - REDIS.HOST=cache.internal\n"
            "      - MY-APP_URL=https://app.internal\n",
            encoding="utf-8",
        )
        sections = _by_id(int_ext.IntegrationsExtractor().extract(root, _opts(root)))
        assert "REDIS.HOST" in sections["int.redis"].l2_md
        assert "MY-APP_URL" in sections["int.other"].l2_md

    def test_compose_environment_null_shape_does_not_warn(self, tmp_path):
        # Round-2 review finding: `environment:` with every entry
        # commented out (or written with nothing after the colon)
        # parses as YAML `None`. The Compose schema itself rejects a
        # null `environment:`, but this is a real-world shape, not a
        # malformed one -- it must stay as silent as the equally-empty
        # `{}`/`[]` forms, not become a new false-positive warning.
        root = tmp_path / "compose-null-env"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: web:1\n"
            "    environment:\n"
            "      # KAFKA_BROKER_URL=commented-out\n",
            encoding="utf-8",
        )
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        assert result.warnings == []
        assert result.sections == []


class TestApiExtractor:
    def test_detects_an_openapi_file(self, repo, tmp_path):
        assert api_ext.ApiExtractor().detect(repo) is True
        empty = tmp_path / "empty6"
        empty.mkdir()
        assert api_ext.ApiExtractor().detect(empty) is False

    def test_one_section_per_tag(self, repo):
        sections = _by_id(api_ext.ApiExtractor().extract(repo, _opts(repo)))
        assert "api.airspace" in sections
        assert sections["api.airspace"].group == "api"
        # Extra coverage: falsifies a version of the tag logic that
        # groups every operation under "surface" regardless of its real
        # tags -- the brief's own untagged-only fixture can't catch that
        # by itself since it never exercises a *tagged* operation.
        assert "api.surface" not in sections

    def test_lists_methods_and_paths(self, repo):
        s = _by_id(api_ext.ApiExtractor().extract(repo, _opts(repo)))["api.airspace"]
        assert "GET" in s.l2_md and "POST" in s.l2_md
        assert "/airspace" in s.l2_md

    def test_untagged_paths_land_in_api_surface(self, tmp_path):
        root = tmp_path / "untagged"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\npaths:\n  /health:\n    get:\n      summary: Health\n",
            encoding="utf-8",
        )
        assert "api.surface" in _by_id(api_ext.ApiExtractor().extract(root, _opts(root)))

    def test_l3_has_no_pipe_table(self, repo):
        for s in api_ext.ApiExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    def test_malformed_openapi_warns(self, tmp_path):
        root = tmp_path / "bad-api"
        root.mkdir()
        (root / "openapi.yaml").write_text("paths: [", encoding="utf-8")
        result = api_ext.ApiExtractor().extract(root, _opts(root))
        assert any("openapi.yaml" in w for w in result.warnings)

    def test_colliding_tag_ids_merge_instead_of_aborting_the_run(self, tmp_path):
        # Important review finding: "My Tag" and "My-Tag" both collapse
        # to `_safe_tag_id` "My-Tag" -- previously two CodeSections with
        # the same id, which core.run()'s duplicate-id guard turns into
        # a fatal CodeIngestError that aborts the whole command (no KB
        # written at all). Operations under colliding tags must now
        # merge into one section instead.
        root = tmp_path / "collide"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\n"
            "paths:\n"
            "  /a:\n"
            "    get:\n      tags: [\"My Tag\"]\n      summary: A\n"
            "  /b:\n"
            "    get:\n      tags: [\"My-Tag\"]\n      summary: B\n",
            encoding="utf-8",
        )
        result = api_ext.ApiExtractor().extract(root, _opts(root))
        sections = _by_id(result)
        assert list(sections) == ["api.My-Tag"]
        body = sections["api.My-Tag"].l2_md
        assert "/a" in body and "/b" in body
        assert any("My-Tag" in w for w in result.warnings)

    def test_servers_wrong_shape_still_warns_when_falsy(self, tmp_path):
        # Minor review finding: `elif servers_raw:` meant a present-but-
        # falsy wrong shape (`servers: {}`) was skipped silently while a
        # present-and-truthy wrong shape (`servers: {url: ...}`) warned.
        # Checking `"servers" in data` first fixes the inconsistency.
        root = tmp_path / "servers-empty-dict"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\nservers: {}\npaths:\n  /health:\n    get:\n      summary: Health\n",
            encoding="utf-8",
        )
        result = api_ext.ApiExtractor().extract(root, _opts(root))
        assert any("servers" in w for w in result.warnings)

    def test_servers_absent_never_warns(self, tmp_path):
        # The other half of the same fix: an absent `servers` key (the
        # common, valid case) must not start warning as a side effect of
        # fixing the falsy-wrong-shape gap above.
        root = tmp_path / "servers-absent"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\npaths:\n  /health:\n    get:\n      summary: Health\n",
            encoding="utf-8",
        )
        result = api_ext.ApiExtractor().extract(root, _opts(root))
        assert result.warnings == []

    def test_servers_url_credential_is_redacted(self, tmp_path):
        # Task review, Important 2: a committed OpenAPI document's
        # servers[*].url is deliberately emitted as literal URL text (the
        # host/path are public information about a committed API
        # contract) -- but a user:pass@ credential sitting in that same
        # URL is not, and must not reach l2_md verbatim.
        root = tmp_path / "servers-credential"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\n"
            "servers:\n"
            "  - url: https://admin:S3CR3TV4LUE@api.example.com\n"
            "paths:\n  /health:\n    get:\n      summary: Health\n",
            encoding="utf-8",
        )
        s = _by_id(api_ext.ApiExtractor().extract(root, _opts(root)))["api.surface"]
        assert "S3CR3TV4LUE" not in s.l2_md
        assert "https://***@api.example.com" in s.l2_md

    def test_operation_summary_with_embedded_newline_does_not_break_the_l2_table(
        self, tmp_path
    ):
        # Task review, Important 3: `_escape_pipe` only ever escaped a
        # literal "|"; an embedded newline (a YAML literal-block
        # `summary:` value) breaks the L2 operations table just as
        # surely, by ending the row (and the table) mid-cell.
        root = tmp_path / "newline-summary"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\n"
            "paths:\n"
            "  /health:\n"
            "    get:\n"
            "      summary: |\n"
            "        first line\n"
            "        second line\n",
            encoding="utf-8",
        )
        s = _by_id(api_ext.ApiExtractor().extract(root, _opts(root)))["api.surface"]
        table_lines = [ln for ln in s.l2_md.splitlines() if ln.startswith("|")]
        # header + separator + exactly one operation row.
        assert len(table_lines) == 3
        assert "first line second line" in table_lines[-1]

    def test_tag_with_embedded_newline_does_not_split_the_heading(self, tmp_path):
        # Minor review finding: `title=tag` was unsanitised while `id`
        # went through `_safe_tag_id` -- a tag containing a literal
        # newline rendered the heading across two lines, which
        # core._render_group() then writes as two lines of a Markdown
        # document. `title` must never contain a newline.
        root = tmp_path / "newline-tag"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\n"
            "paths:\n"
            "  /x:\n"
            '    get:\n      tags: ["Ops\\nInjected"]\n      summary: X\n',
            encoding="utf-8",
        )
        result = api_ext.ApiExtractor().extract(root, _opts(root))
        assert len(result.sections) == 1
        assert "\n" not in result.sections[0].title
        # Round-2 review finding: `summary` still interpolated the raw
        # tag even after `title` was fixed -- the same field-
        # sanitisation asymmetry Minor 4 closed, one field short. A
        # newline in `summary` reaches `_manifest.yaml` via core.run().
        assert "\n" not in result.sections[0].summary
