# Coding style — shared

Language-agnostic rules, scaffolded into every dev repo. A file under
`docs/conventions/<lang>/` extends its counterpart here; where the two
disagree, the language file wins. Record repo-specific deviations in the
relevant `docs/conventions/<lang>.local.md`.

## Immutability (critical)

ALWAYS create new objects, NEVER mutate existing ones:

```
// Pseudocode
WRONG:  modify(original, field, value) → changes original in-place
CORRECT: update(original, field, value) → returns new copy with change
```

Rationale: Immutable data prevents hidden side effects, makes debugging easier, and enables safe concurrency.

## Core principles

### KISS (keep it simple)

- Prefer the simplest solution that actually works
- Avoid premature optimization
- Optimize for clarity over cleverness

### DRY (don't repeat yourself)

- Extract repeated logic into shared functions or utilities
- Avoid copy-paste implementation drift
- Introduce abstractions when repetition is real, not speculative

### YAGNI (you aren't gonna need it)

- Do not build features or abstractions before they are needed
- Avoid speculative generality
- Start simple, then refactor when the pressure is real

## File organization

MANY SMALL FILES > FEW LARGE FILES:
- High cohesion, low coupling
- 200-400 lines typical, 800 max
- Extract utilities from large modules
- Organize by feature/domain, not by type

## Error handling

ALWAYS handle errors comprehensively:
- Handle errors explicitly at every level
- Provide user-friendly error messages in UI-facing code
- Log detailed error context on the server side
- Never silently swallow errors

## Input validation

ALWAYS validate at system boundaries:
- Validate all user input before processing
- Use schema-based validation where available
- Fail fast with clear error messages
- Never trust external data (API responses, user input, file content)

## Naming conventions

- Variables and functions: descriptive names, not abbreviations
- Booleans: prefer `is`, `has`, `should`, or `can` prefixes
- Constants: clearly marked as such (a naming convention or the
  language's `const`/`final`/`readonly` mechanism)
- Casing rules live in each language's coding-style.md.

## Code smells to avoid

### Deep nesting

Prefer early returns over nested conditionals once the logic starts stacking.

### Magic numbers

Use named constants for meaningful thresholds, delays, and limits.

### Long functions

Split large functions into focused pieces with clear responsibilities.

## Code quality checklist

Before marking work complete:
- [ ] Code is readable and well-named
- [ ] Functions are small (<50 lines)
- [ ] Files are focused (<800 lines)
- [ ] No deep nesting (>4 levels)
- [ ] Proper error handling
- [ ] No hardcoded values (use constants or config)
- [ ] No mutation (immutable patterns used)
