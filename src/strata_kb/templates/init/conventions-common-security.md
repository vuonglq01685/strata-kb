# Security — shared

Language-agnostic rules, scaffolded into every dev repo. A file under
`docs/conventions/<lang>/` extends its counterpart here; where the two
disagree, the language file wins. Record repo-specific deviations in the
relevant `docs/conventions/<lang>.local.md`.

## Mandatory security checks

Before any commit — this is the A5 merge-risk checklist in `/dev-handover`:
- [ ] No hardcoded secrets (API keys, passwords, tokens)
- [ ] All user inputs validated
- [ ] SQL injection prevention (parameterized queries)
- [ ] XSS prevention (sanitized HTML)
- [ ] CSRF protection enabled
- [ ] Authentication/authorization verified
- [ ] Rate limiting on all endpoints
- [ ] Error messages don't leak sensitive data

## Secret management

- NEVER hardcode secrets in source code
- ALWAYS use environment variables or a secret manager
- Validate that required secrets are present at startup
- Rotate any secrets that may have been exposed

## Security response protocol

If security issue found:
1. STOP immediately
2. Raise it as a BLOCKER in the task review (A3, `/dev-execute`) or the merge-risk review (A5, `/dev-handover`)
3. Fix CRITICAL issues before continuing
4. Rotate any exposed secrets
5. Review entire codebase for similar issues
