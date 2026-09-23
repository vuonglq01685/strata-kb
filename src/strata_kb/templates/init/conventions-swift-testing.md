> This file extends [common/testing.md](../common/testing.md) with Swift-specific content.

# Swift testing

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/swift.local.md`.

## Ground rules

- XCTest (or `swift-testing` where the repo has adopted it); AAA shape,
  one behaviour per test.
- Names describe the behaviour: `func test_rejectsExpiredToken()`, not
  `func test2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Framework

Use **Swift Testing** (`import Testing`) for new tests. Use `@Test` and
`#expect`:

```swift
@Test("User creation validates email")
func userCreationValidatesEmail() throws {
    #expect(throws: ValidationError.invalidEmail) {
        try User(email: "not-an-email")
    }
}
```

## Test isolation

Each test gets a fresh instance — set up in `init`, tear down in
`deinit`. No shared mutable state between tests.

## Parameterized tests

```swift
@Test("Validates formats", arguments: ["json", "xml", "csv"])
func validatesFormat(format: String) throws {
    let parser = try Parser(format: format)
    #expect(parser.isValid)
}
```

## Coverage

```bash
swift test --enable-code-coverage
```
