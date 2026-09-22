> This file extends [common/coding-style.md](../common/coding-style.md) with Dart / Flutter-specific content.

# Dart / Flutter coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dart.local.md`.

## Naming

- Types, enums, extensions: `PascalCase`. Variables, functions,
  parameters: `camelCase`. Files: `snake_case.dart`.
- Booleans read as predicates (`isReady`, `hasPending`).
- Widgets are nouns naming what they render (`UserAvatar`, not
  `BuildUserAvatar`).
- `SCREAMING_SNAKE_CASE` for constants declared with `const` at top
  level; prefix private members with `_`.
- Extension names describe the type they extend (`StringExtensions`,
  not `MyHelpers`).
- Named constructors: `camelCase` (`User.fromJson`).
- Typedefs: `PascalCase`.
- Library names: `snake_case`.

## Module structure

- Organise by feature/domain (`lib/<feature>/`), not by widget/model/
  service layering across the whole app.
- Keep widgets and classes small and cohesive; a file past ~400 lines
  is a signal to split.
- Prefer composition over deep widget-inheritance chains.

## Formatting

- Line length: 80 characters (`dart format` default).
- Trailing commas on multi-line argument/parameter lists to improve
  diffs and formatting.
- The formatter and linter are fixed by the `## Linting (preset)`
  section of `docs/conventions/dart.md`; that preset wins over any
  tool named here.

## Immutability

- Prefer `final` for local variables and `const` for compile-time
  constants.
- Use `const` constructors wherever all fields are `final`.
- Return unmodifiable collections from public APIs
  (`List.unmodifiable`, `Map.unmodifiable`).
- Use `copyWith()` for state mutations in immutable state classes.

```dart
// BAD
var count = 0;
List<String> items = ['a', 'b'];

// GOOD
final count = 0;
const items = ['a', 'b'];
```

## Null safety

- Avoid `!` (bang operator) — prefer `?.`, `??`, `if (x != null)`, or
  Dart 3 pattern matching; reserve `!` only where a null value is a
  programming error and crashing is the right behaviour.
- Avoid `late` unless initialization is guaranteed before first use
  (prefer nullable or constructor init).
- Use `required` for constructor parameters that must always be
  provided.

```dart
// BAD — crashes at runtime if user is null
final name = user!.name;

// GOOD — null-aware operators
final name = user?.name ?? 'Unknown';

// GOOD — Dart 3 pattern matching (exhaustive, compiler-checked)
final name = switch (user) {
  User(:final name) => name,
  null => 'Unknown',
};

// GOOD — early-return null guard
String getUserName(User? user) {
  if (user == null) return 'Unknown';
  return user.name; // promoted to non-null after the guard
}
```

## Sealed types and pattern matching (Dart 3+)

Use sealed classes to model closed state hierarchies:

```dart
sealed class AsyncState<T> {
  const AsyncState();
}

final class Loading<T> extends AsyncState<T> {
  const Loading();
}

final class Success<T> extends AsyncState<T> {
  const Success(this.data);
  final T data;
}

final class Failure<T> extends AsyncState<T> {
  const Failure(this.error);
  final Object error;
}
```

Always use exhaustive `switch` with sealed types — no default/wildcard:

```dart
// BAD
if (state is Loading) { ... }

// GOOD
return switch (state) {
  Loading() => const CircularProgressIndicator(),
  Success(:final data) => DataWidget(data),
  Failure(:final error) => ErrorWidget(error.toString()),
};
```

## Async / futures

- Always `await` Futures or explicitly call `unawaited()` to signal
  intentional fire-and-forget.
- Never mark a function `async` if it never `await`s anything.
- Use `Future.wait` / `Future.any` for concurrent operations.
- Check `context.mounted` before using `BuildContext` after any
  `await` (Flutter 3.7+).

```dart
// BAD — ignoring Future
fetchData(); // fire-and-forget without marking intent

// GOOD
unawaited(fetchData()); // explicit fire-and-forget
await fetchData();      // or properly awaited
```

## Imports

- Use `package:` imports throughout — never relative imports (`../`)
  for cross-feature or cross-layer code.
- Order: `dart:` → external `package:` → internal `package:` (same
  package).
- No unused imports — `dart analyze` enforces this with
  `unused_import`.

## Code generation

- Generated files (`.g.dart`, `.freezed.dart`, `.gr.dart`) must be
  committed or gitignored consistently — pick one strategy per
  project.
- Never manually edit generated files.
- Keep generator annotations (`@JsonSerializable`, `@freezed`,
  `@riverpod`, etc.) on the canonical source file only.

## Error handling

- Throw typed exceptions (a custom `Exception` subclass), never a bare
  `String`; never swallow a `Future` — every one is awaited, returned,
  or explicitly `.catchError`-handled.
- Fail fast at boundaries: validate external data (API responses, user
  input) before it crosses into typed models.
- `catch` only what the code can handle; rethrow otherwise, preserving
  the stack trace (`Error.throwWithStackTrace` or rethrow `on E`).
  Never catch `Error` subtypes — they indicate programming bugs, not
  recoverable failures.
- Use `Result`-style types or sealed classes for recoverable errors;
  avoid using exceptions for control flow.
- Specify exception types in `on` clauses — never use bare
  `catch (e)`.

```dart
// BAD
try {
  await fetchUser();
} catch (e) {
  log(e.toString());
}

// GOOD
try {
  await fetchUser();
} on NetworkException catch (e) {
  log('Network error: ${e.message}');
} on NotFoundException {
  handleNotFound();
}
```

## Logging

- Use `dart:developer`'s `log()` (structured, named); never
  `print` for diagnostics in committed code.
- Log where the error is handled, with enough context to act on.
