# Java coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/java.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/java.local.md` wins over both.

| Topic | Java | Shared |
|---|---|---|
| Coding style | [java/coding-style.md](java/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [java/patterns.md](java/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [java/security.md](java/security.md) | [common/security.md](common/security.md) |
| Testing | [java/testing.md](java/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [java/hooks.md](java/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```java
static final int MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Linting (preset)

The preset below is the target strength. When this repo has no linter,
the first task of a dev plan wires the preset below into the repo's
build tool and records the command as `cmd.lint`. Where `cmd.lint` fails
on the untouched tree, narrow `select` / rules / warning caps to what
passes, and list each narrowed rule under `## Findings` in the PR body
as a tightening still owed. Format = spotless (google-java-format),
wired for both build tools. Lint = checkstyle with the built-in Google
ruleset, wired for Gradle below; the Maven variant covers formatting
only, so a Maven repo's `cmd.lint` is format-only until a checkstyle
plugin is added — record that gap as a finding in the PR.

Gradle (`build.gradle`) — merge these blocks into the existing file;
assumes the `java` plugin and a `repositories { }` block are already
declared there:

```groovy
plugins {
    id "com.diffplug.spotless" version "7.0.2"
    id "checkstyle"
}

configurations { checkstyleConfig }

dependencies {
    checkstyleConfig("com.puppycrawl.tools:checkstyle:10.21.0") { transitive = false }
}

spotless {
    java { googleJavaFormat() }
}

checkstyle {
    toolVersion = "10.21.0"
    config = resources.text.fromArchiveEntry(configurations.checkstyleConfig, "google_checks.xml")
}
```

Set `maxWarnings = 0` once the tree is clean — with `google_checks.xml`
at severity `warning`, a pre-existing repo fails on day one otherwise.
Until then checkstyle reports but cannot fail — list it under
`## Findings` as a tightening still owed.

`build.gradle.kts` is also a detected manifest, but the block above is
Groovy DSL. The Kotlin DSL needs different syntax for `configurations
{ }` and `resources.text.fromArchiveEntry(...)` — do not paste the
block above into a `.kts` file as-is; translate it by hand.

Maven (`pom.xml`, inside `<build><plugins>`):

```xml
<plugin>
  <groupId>com.diffplug.spotless</groupId>
  <artifactId>spotless-maven-plugin</artifactId>
  <version>2.44.0</version>
  <configuration>
    <java><googleJavaFormat/></java>
  </configuration>
</plugin>
```

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.java]
indent_size = 2
```

Run:

```
./gradlew spotlessCheck checkstyleMain    # Gradle
mvn spotless:check                        # Maven
```

Record as `cmd.lint`: `./gradlew spotlessCheck checkstyleMain` (Gradle)
or `mvn spotless:check` (Maven).
