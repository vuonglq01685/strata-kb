> This file extends [common/coding-style.md](../common/coding-style.md) with Java-specific content.

# Java coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/java.local.md`.

## Standards

- Member order: constants, fields, constructors, public methods,
  protected, private.
- The formatter and linter are fixed by the `## Linting (preset)` section of
  `docs/conventions/java.md`; that preset wins over any tool named here.

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

## Immutability

- Prefer `record` for value types (Java 16+)
- Mark fields `final` by default — use mutable state only when required
- Return defensive copies from public APIs: `List.copyOf()`, `Map.copyOf()`, `Set.copyOf()`
- Copy-on-write: return new instances rather than mutating existing ones

```java
// GOOD — immutable value type
public record OrderSummary(Long id, String customerName, BigDecimal total) {}

// GOOD — final fields, no setters
public class Order {
    private final Long id;
    private final List<LineItem> items;

    public List<LineItem> getItems() {
        return List.copyOf(items);
    }
}
```

## Modern Java features

Use modern language features where they improve clarity:
- **Records** for DTOs and value types (Java 16+)
- **Sealed classes** for closed type hierarchies (Java 17+)
- **Pattern matching** with `instanceof` — no explicit cast (Java 16+)
- **Text blocks** for multi-line strings — SQL, JSON templates (Java 15+)
- **Switch expressions** with arrow syntax (Java 14+)
- **Pattern matching in switch** — exhaustive sealed type handling (Java 21+)

```java
// Pattern matching instanceof
if (shape instanceof Circle c) {
    return Math.PI * c.radius() * c.radius();
}

// Sealed type hierarchy
public sealed interface PaymentMethod permits CreditCard, BankTransfer, Wallet {}

// Switch expression
String label = switch (status) {
    case ACTIVE -> "Active";
    case SUSPENDED -> "Suspended";
    case CLOSED -> "Closed";
};
```

## Optional usage

- Return `Optional<T>` from finder methods that may have no result
- Use `map()`, `flatMap()`, `orElseThrow()` — never call `get()` without `isPresent()`
- Never use `Optional` as a field type or method parameter

```java
// GOOD
return repository.findById(id)
    .map(ResponseDto::from)
    .orElseThrow(() -> new OrderNotFoundException(id));

// BAD — Optional as parameter
public void process(Optional<String> name) {}
```

## Streams

- Use streams for transformations; keep pipelines short (3-4 operations max)
- Prefer method references when readable: `.map(Order::getTotal)`
- Avoid side effects in stream operations
- For complex logic, prefer a loop over a convoluted stream pipeline

## Error handling

- Throw specific exceptions; never `catch (Exception e) {}` — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate arguments where data enters
  (`Objects.requireNonNull`, explicit checks with messages naming the
  offending value).
- Catch only what the code can handle; otherwise wrap and rethrow with
  the original as cause.
- Prefer unchecked exceptions for domain errors; create domain-specific
  exceptions extending `RuntimeException` with context in the message.
- Avoid broad `catch (Exception e)` outside top-level handlers.

```java
public class OrderNotFoundException extends RuntimeException {
    public OrderNotFoundException(Long id) {
        super("Order not found: id=" + id);
    }
}
```

## Logging

- Use SLF4J (`LoggerFactory.getLogger(X.class)`); never
  `System.out.println` in committed code.
- Use parameterised messages (`log.info("user {} created", id)`), not
  string concatenation.
