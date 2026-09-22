> This file extends [common/security.md](../common/security.md) with Swift-specific content.

# Swift security

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/swift.local.md`.

## Secret management

- Use **Keychain Services** for sensitive data (tokens, passwords, keys)
  — never `UserDefaults`.
- Use environment variables or `.xcconfig` files for build-time secrets.
- Never hardcode secrets in source — decompilation tools extract them
  trivially.

```swift
let apiKey = ProcessInfo.processInfo.environment["API_KEY"]
guard let apiKey, !apiKey.isEmpty else {
    fatalError("API_KEY not configured")
}
```

## Transport security

- App Transport Security (ATS) is enforced by default — do not disable
  it.
- Use certificate pinning for critical endpoints.
- Validate all server certificates.

## Input validation

- Sanitize all user input before display to prevent injection.
- Use `URL(string:)` with validation rather than force-unwrapping.
- Validate data from external sources (APIs, deep links, pasteboard)
  before processing.
