> This file extends [common/coding-style.md](../common/coding-style.md) with TypeScript / JavaScript-specific content.

# TypeScript / JavaScript coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/ts.local.md`.

## Naming

- Variables and functions: `camelCase`, descriptive; booleans read as
  predicates (`isReady`, `hasPending`, `shouldRetry`).
- Types, interfaces, classes, enums, React components: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE` for true module-level constants.
- Files: follow the repo's dominant style; when there is none,
  `kebab-case.ts` for modules, `PascalCase.tsx` for components.

## Module structure

- Organise by feature/domain, not by technical layer.
- One clear responsibility per file; ~200–400 lines typical, 800 max —
  extract before crossing it.
- Prefer named exports; a default export only for the file's single main
  artifact (e.g. a component).
- No deep relative import chains (`../../../`) — use the repo's path
  aliases when it has them.

## Types and interfaces

Use types to make public APIs, shared models, and component props
explicit, readable, and reusable.

### Public APIs

- Add parameter and return types to exported functions, shared
  utilities, and public class methods.
- Let TypeScript infer obvious local variable types.
- Extract repeated inline object shapes into named types or
  interfaces.

```typescript
// WRONG: Exported function without explicit types
export function formatUser(user) {
  return `${user.firstName} ${user.lastName}`
}

// CORRECT: Explicit types on public APIs
interface User {
  firstName: string
  lastName: string
}

export function formatUser(user: User): string {
  return `${user.firstName} ${user.lastName}`
}
```

### Interfaces vs. type aliases

- Use `interface` for object shapes that may be extended or
  implemented.
- Use `type` for unions, intersections, tuples, mapped types, and
  utility types.
- Prefer string literal unions over `enum` unless an `enum` is
  required for interoperability.

```typescript
interface User {
  id: string
  email: string
}

type UserRole = 'admin' | 'member'
type UserWithRole = User & {
  role: UserRole
}
```

### Avoid `any`

- Avoid `any` in application code.
- Use `unknown` for external or untrusted input, then narrow it
  safely.
- Use generics when a value's type depends on the caller.

```typescript
// WRONG: any removes type safety
function getErrorMessage(error: any) {
  return error.message
}

// CORRECT: unknown forces safe narrowing
function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }

  return 'Unexpected error'
}
```

### React props

- Define component props with a named `interface` or `type`.
- Type callback props explicitly.
- Do not use `React.FC` unless there is a specific reason to do so.

```typescript
interface User {
  id: string
  email: string
}

interface UserCardProps {
  user: User
  onSelect: (id: string) => void
}

function UserCard({ user, onSelect }: UserCardProps) {
  return <button onClick={() => onSelect(user.id)}>{user.email}</button>
}
```

### JavaScript files

- In `.js` and `.jsx` files, use JSDoc when types improve clarity and
  a TypeScript migration is not practical.
- Keep JSDoc aligned with runtime behavior.

```javascript
/**
 * @param {{ firstName: string, lastName: string }} user
 * @returns {string}
 */
export function formatUser(user) {
  return `${user.firstName} ${user.lastName}`
}
```

## Immutability

Use the spread operator for immutable updates:

```typescript
interface User {
  id: string
  name: string
}

// WRONG: Mutation
function updateUser(user: User, name: string): User {
  user.name = name // MUTATION!
  return user
}

// CORRECT: Immutability
function updateUser(user: Readonly<User>, name: string): User {
  return {
    ...user,
    name
  }
}
```

## Error handling

- Throw `Error` subclasses, never strings; never swallow a rejection —
  every promise is awaited, returned, or explicitly `.catch`-handled.
- Fail fast at boundaries: validate external data (API responses, user
  input, file content) before it crosses into typed code.
- `catch` only what the code can handle; rethrow with cause otherwise:
  `throw new AppError("...", { cause: err })`.

Narrow `unknown` errors safely with async/await and try/catch:

```typescript
interface User {
  id: string
  email: string
}

declare function riskyOperation(userId: string): Promise<User>

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }

  return 'Unexpected error'
}

const logger = {
  error: (message: string, error: unknown) => {
    // Replace with your production logger (for example, pino or winston).
  }
}

async function loadUser(userId: string): Promise<User> {
  try {
    const result = await riskyOperation(userId)
    return result
  } catch (error: unknown) {
    logger.error('Operation failed', error)
    throw new Error(getErrorMessage(error))
  }
}
```

## Input validation

Use Zod for schema-based validation and infer types from the schema:

```typescript
import { z } from 'zod'

const userSchema = z.object({
  email: z.string().email(),
  age: z.number().int().min(0).max(150)
})

type UserInput = z.infer<typeof userSchema>

const validated: UserInput = userSchema.parse(input)
```

## Console.log

- No `console.log` statements in production code.
- Use proper logging libraries instead.
- See [hooks.md](hooks.md) for automatic detection.

## Logging

- Use the repo's logging facility; never `console.log` in committed
  code (a structured logger, or nothing).
- Log where the error is handled, with enough context to act on.
