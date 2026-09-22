> This file extends [common/patterns.md](../common/patterns.md) with PHP-specific content.

# PHP patterns

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/php.local.md`.

## Thin controllers, explicit services

- Keep controllers focused on transport: auth, validation, serialization,
  status codes.
- Move business rules into application/domain services that are easy to
  test without HTTP bootstrapping.

## DTOs and value objects

- Replace shape-heavy associative arrays with DTOs for requests,
  commands, and external API payloads.
- Use value objects for money, identifiers, date ranges, and other
  constrained concepts.

## Dependency injection

- Depend on interfaces or narrow service contracts, not framework
  globals.
- Pass collaborators through constructors so services are testable
  without service-locator lookups.

## Boundaries

- Isolate ORM models from domain decisions when the model layer is doing
  more than persistence.
- Wrap third-party SDKs behind small adapters so the rest of the
  codebase depends on your contract, not theirs.
