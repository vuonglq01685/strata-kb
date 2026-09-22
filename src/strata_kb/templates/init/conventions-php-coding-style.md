> This file extends [common/coding-style.md](../common/coding-style.md) with PHP-specific content.

# PHP coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/php.local.md`.

## Naming

- Classes, interfaces, traits, enums: `PascalCase`; one per file, file
  named after it (PSR-4).
- Methods and properties: `camelCase`; booleans read as predicates
  (`isReady`, `hasPending`).
- Constants: `UPPER_SNAKE_CASE`.
- Namespaces mirror the directory layout (PSR-4 autoloading).

## Module structure

- Organise by feature/domain, not by technical layer alone.
- One class per file; keep classes focused — extract before ~400 lines.
- Depend on interfaces at boundaries; constructor injection over global
  state and static calls.

## Standards

- Follow **PSR-12** formatting and naming conventions.
- Prefer `declare(strict_types=1);` in application code.
- Use scalar type hints, return types, and typed properties everywhere
  new code permits.
- The formatter and linter are fixed by the `## Linting (preset)` section
  of `docs/conventions/php.md`; that preset wins over any tool named
  here.
- Static analysis (PHPStan or Psalm) if the repo has one configured; the
  level is the repo's, not this file's.
- Keep Composer scripts checked in so the same commands run locally and
  in CI.

## Immutability

- Prefer immutable DTOs and value objects for data crossing service
  boundaries.
- Use `readonly` properties or immutable constructors for
  request/response payloads where possible.
- Keep arrays for simple maps; promote business-critical structures into
  explicit classes.

## Imports

- Add `use` statements for all referenced classes, interfaces, and
  traits.
- Avoid relying on the global namespace unless the project explicitly
  prefers fully qualified names.

## Error handling

- Throw specific exception classes; never empty `catch` blocks — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate input where data enters and throw
  with a message naming the offending value.
- Catch only what the code can handle; otherwise wrap and rethrow with
  `previous:` set to the original.
- Avoid returning `false`/`null` as hidden error channels in new code —
  throw instead.
- Convert framework/request input into validated DTOs before it reaches
  domain logic.

## Logging

- Use a PSR-3 logger; never `echo`/`var_dump`/`print_r` for diagnostics
  in committed code.
- Log where the error is handled, with context array
  (`$logger->error('resolve failed', ['ref' => $ref])`).
