# PHP coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/php.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

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

## Error handling

- Throw specific exception classes; never empty `catch` blocks — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate input where data enters and throw
  with a message naming the offending value.
- Catch only what the code can handle; otherwise wrap and rethrow with
  `previous:` set to the original.

## Logging

- Use a PSR-3 logger; never `echo`/`var_dump`/`print_r` for diagnostics
  in committed code.
- Log where the error is handled, with context array
  (`$logger->error('resolve failed', ['ref' => $ref])`).

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```php
const MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- PHPUnit, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `testRejectsExpiredToken()`, not
  `testToken2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. Where `cmd.lint` fails on the untouched tree, narrow `select` /
rules / warning caps to what passes, and list each narrowed rule under
`## Findings` in the PR body as a tightening still owed.

`.php-cs-fixer.dist.php`:

```php
<?php

$finder = PhpCsFixer\Finder::create()
    ->in(__DIR__)
    ->exclude('vendor');

return (new PhpCsFixer\Config())
    ->setRules([
        '@PSR12' => true,
    ])
    ->setFinder($finder);
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

[*.php]
indent_size = 4
```

Install and run:

```
composer require --dev friendsofphp/php-cs-fixer
vendor/bin/php-cs-fixer check --diff
```

Record as `cmd.lint`: `vendor/bin/php-cs-fixer check --diff`
