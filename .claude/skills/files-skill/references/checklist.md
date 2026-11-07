# Convention Checklist

Walk this checklist against the sampled files in Phase 3. Skip items that don't apply to the language or project type. For each applicable item, record: pattern observed, frequency/scope, example file references.

## Naming

- File naming (snake_case, kebab-case, PascalCase, etc., and whether it differs by file type).
- Module/package naming.
- Type/class naming.
- Function/method naming — including verb conventions (`getX` vs `fetchX` vs `loadX`, `isX` vs `hasX`, etc.).
- Variable naming, including scope-based conventions (private prefixes, constants).
- Test naming — file naming and individual test naming.
- Constant naming (SCREAMING_SNAKE_CASE vs other).

## File and directory organization

- Where do tests live? (Co-located, separate tree, mirror structure.)
- Where do types/models live relative to code that uses them?
- Are there per-feature folders, per-layer folders, or a mix?
- Where does shared/utility code live, and is that location explicit or a catch-all?
- Is there a public API surface explicitly exposed (index files, re-exports, `__init__.py`, `lib.rs`)?
- Where does config live? Where do constants live?

## Module boundaries and dependencies

- How do modules import from each other? Relative vs absolute paths?
- Is there a clear dependency direction (e.g., domain → infra, never reverse)?
- Are there circular dependencies? (Note as a contradiction if present.)
- Are there layers that should be isolated (e.g., domain layer that doesn't import framework code)?

## Type usage

- Are types pervasive, optional, or absent? (Type hints in Python, TypeScript strictness, etc.)
- Are types defined inline or in dedicated files?
- Generics / type parameters — frequent or rare? Style?
- Custom type aliases — used heavily or avoided?
- Nullability convention (`Option`, `Optional`, `?`, `| null`, `| undefined` — which one, where).

## Error handling

- Exceptions vs `Result`/`Either` types vs error codes vs panics.
- How are errors propagated up the stack?
- Are there custom error types, or do callers receive framework errors?
- Logging on error paths — what gets logged, at what level?
- User-facing error formatting — separate concern or mixed in?

## Async and concurrency

- async/await, callbacks, promises, futures, channels?
- Where does the boundary between sync and async code sit?
- Cancellation handling (timeouts, cancel tokens, signals)?
- State sharing across concurrent tasks (locks, actors, message passing)?

## State management (for apps with UI or state)

- What state library/pattern? (Redux, Riverpod, Provider, signals, MobX, Zustand, plain hooks, etc.)
- Where does state live in the architecture?
- Are mutations explicit or implicit?

## Data layer

- ORM, query builder, raw queries, or mix?
- Where do schemas / migrations live?
- Validation — at the API boundary, in the model, both?
- Serialization conventions (JSON shape, naming case for fields).

## Testing

- Test framework(s) in use.
- Unit vs integration vs end-to-end split — visible in folder structure?
- Mock/stub conventions (libraries used, hand-rolled, dependency injection?).
- Fixture / test data conventions.
- What's the test coverage level (rough — high, medium, sparse, untested)?
- Are tests treated as documentation? (Descriptive names, scenario-style structure?)

## Comments and documentation

- Inline comment density.
- Doc comments on public APIs — convention (JSDoc, docstrings, dartdoc, rustdoc) and whether they're enforced.
- README presence and completeness.
- ADRs (architectural decision records) — present? Where?
- "Why" vs "what" comments — which dominates?

## Tooling and config

- Formatter in use (and config).
- Linter in use (and which rules are turned on/off).
- Pre-commit hooks?
- CI shape (very brief — what runs on PR, what runs on merge).

## Code style micro-patterns

- Function length tendency (short and many, vs long and few).
- Early returns vs nested conditionals.
- Composition vs inheritance for code reuse.
- Immutability — preferred, sometimes, rarely?
- Pure functions vs methods on objects — which dominates in business logic?

## Logging and observability

- Logging library and conventions (structured, unstructured, level usage).
- Tracing / metrics — present? Library?
- What gets logged at info, warn, error?

## Security and secrets

- How are secrets accessed (env vars, secrets manager, config files)?
- Any visible patterns around input validation, sanitization, auth checks?
- (Do not deeply audit security — just note conventions.)
