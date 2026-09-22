> This file extends [common/hooks.md](../common/hooks.md) with Java-specific content.

# Java hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/java.local.md`.

## PostToolUse hooks

Configure in `.claude/settings.json` (this repo's, committed):

- **google-java-format**: Auto-format `.java` files after edit
- **checkstyle**: Run style checks after editing Java files
- **./mvnw compile** or **./gradlew compileJava**: Verify compilation after changes
