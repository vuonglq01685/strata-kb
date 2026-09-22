# Testing — shared

Language-agnostic rules, scaffolded into every dev repo. A file under
`docs/conventions/<lang>/` extends its counterpart here; where the two
disagree, the language file wins. Record repo-specific deviations in the
relevant `docs/conventions/<lang>.local.md`.

## Minimum test coverage: 80%

Test Types (ALL required):
1. **Unit tests** - Individual functions, utilities, components
2. **Integration tests** - API endpoints, database operations
3. **E2E tests** - Critical user flows (framework chosen per language)

## Test-driven development

MANDATORY workflow:
1. Write test first (RED)
2. Run test - it should FAIL
3. Write minimal implementation (GREEN)
4. Run test - it should PASS
5. Refactor (IMPROVE)
6. Verify coverage (80%+)

## Troubleshooting test failures

1. Re-read the task block in the plan: the failing test must exercise the AC it names, nothing wider
2. Check test isolation
3. Verify mocks are correct
4. Fix implementation, not tests (unless tests are wrong)

## Test structure (AAA pattern)

Prefer Arrange-Act-Assert structure for tests:

```typescript
test('calculates similarity correctly', () => {
  // Arrange
  const vector1 = [1, 0, 0]
  const vector2 = [0, 1, 0]

  // Act
  const similarity = calculateCosineSimilarity(vector1, vector2)

  // Assert
  expect(similarity).toBe(0)
})
```

### Test naming

Use descriptive names that explain the behavior under test:

```typescript
test('returns empty array when no markets match query', () => {})
test('throws error when API key is missing', () => {})
test('falls back to substring search when Redis is unavailable', () => {})
```
