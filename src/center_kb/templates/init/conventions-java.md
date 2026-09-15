# Java coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/java.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Packages: all-lowercase, no underscores (`com.acme.billing`).
- Classes, interfaces, enums, records: `PascalCase`; exceptions end in
  `Exception`.
- Methods and fields: `camelCase`; booleans read as predicates
  (`isReady`, `hasPending`).
- Constants (`static final`): `UPPER_SNAKE_CASE`.

## Module structure

- Organise packages by feature/domain, not by technical layer alone.
- One top-level type per file; keep classes focused — extract before a
  class grows past ~400 lines.
- Depend on interfaces at boundaries; keep constructors injectable (no
  hidden `new` of collaborators in business logic).

## Error handling

- Throw specific exceptions; never `catch (Exception e) {}` — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate arguments where data enters
  (`Objects.requireNonNull`, explicit checks with messages naming the
  offending value).
- Catch only what the code can handle; otherwise wrap and rethrow with
  the original as cause.

## Logging

- Use SLF4J (`LoggerFactory.getLogger(X.class)`); never
  `System.out.println` in committed code.
- Use parameterised messages (`log.info("user {} created", id)`), not
  string concatenation.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```java
static final int MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- JUnit 5, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `rejectsExpiredToken()`, not `test2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

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
