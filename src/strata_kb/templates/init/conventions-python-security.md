> This file extends [common/security.md](../common/security.md) with Python-specific content.

# Python security

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`.

## Secret management

```python
import os

api_key = os.environ["OPENAI_API_KEY"]  # raises KeyError if missing — never .get()
```

## Security scanning

- Use **bandit** for static security analysis:
  ```bash
  bandit -r src/
  ```
