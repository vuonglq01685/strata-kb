> This file extends [common/security.md](../common/security.md) with PHP-specific content.

# PHP security

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/php.local.md`.

## Input and output

- Validate request input at the framework boundary (`FormRequest`,
  Symfony Validator, or explicit DTO validation).
- Escape output in templates by default; treat raw HTML rendering as an
  exception that must be justified.
- Never trust query params, cookies, headers, or uploaded file metadata
  without validation.

## Database safety

- Use prepared statements (`PDO`, Doctrine, Eloquent query builder) for
  all dynamic queries.
- Avoid string-building SQL in controllers/views.
- Scope ORM mass-assignment carefully and whitelist writable fields.

## Secrets and dependencies

- Load secrets from environment variables or a secret manager, never
  from committed config files.
- Run `composer audit` in CI and review new package maintainer trust
  before adding dependencies.
- Pin major versions deliberately and remove abandoned packages quickly.

## Auth and session safety

- Use `password_hash()` / `password_verify()` for password storage.
- Regenerate session identifiers after authentication and privilege
  changes.
- Enforce CSRF protection on state-changing web requests.
