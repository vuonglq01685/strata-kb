# <Title — one line, imperative, with identifier>

## Summary
<1–2 lines business summary>

## User Story
As a <role>, I want <capability>, so that <value>.

## Background / Business context
<context; every industry-standard claim cites `doc-id §section`>

## Acceptance Criteria
- [ ] AC1 … (cite `doc-id §section` when it touches a standard)
- [ ] AC2 …

## Use cases
### Main flow
### Alternate / exception flows

## Sequence diagram
```mermaid
sequenceDiagram
  …
```

## Business flow
```mermaid
flowchart TD
  …
```

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - <repo:doc-id §section>
  tags: [ … ]
```

## Definition of Ready
- [ ] Story, ACs, use cases, both diagrams present
- [ ] Every citation resolves at the pinned version (kb ticket lint PASS)
- [ ] No stale refs
