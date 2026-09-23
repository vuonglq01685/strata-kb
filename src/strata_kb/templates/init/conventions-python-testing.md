> This file extends [common/testing.md](../common/testing.md) with Python-specific content.

# Python testing

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`.

## Ground rules

- pytest, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `test_rejects_expired_token`, not
  `test_token_2`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Coverage

```bash
pytest --cov=src --cov-report=term-missing
```

## Test organization

Use `pytest.mark` for test categorization:

```python
import pytest

@pytest.mark.unit
def test_calculate_total():
    ...

@pytest.mark.integration
def test_database_connection():
    ...
```
