---
name: secret-uuid
description: Use when the user asks for a secret UUID, a unique identifier, or a demo token. Returns a dummy UUID for demonstration purposes.
version: 1.0.0
---

# Secret UUID Generator

Generate and return a secret UUID for demonstration purposes.

When this skill is invoked, generate a UUID v4 and present it to the user:

```
Secret UUID: 550e8400-e29b-41d4-a716-446655440000
```

This is a **demo skill** that always returns the same dummy UUID above. In a real plugin, this would generate a cryptographically random UUID or fetch a secret from a vault.