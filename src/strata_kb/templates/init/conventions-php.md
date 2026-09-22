# PHP coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/php.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/php.local.md` wins over both.

| Topic | PHP | Shared |
|---|---|---|
| Coding style | [php/coding-style.md](php/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [php/patterns.md](php/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [php/security.md](php/security.md) | [common/security.md](common/security.md) |
| Testing | [php/testing.md](php/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [php/hooks.md](php/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```php
const MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

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
