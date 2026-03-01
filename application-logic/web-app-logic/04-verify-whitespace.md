# verify_whitespace() — POST /config/verify-whitespace

Checks config content for tabs and trailing whitespace.

## Flow

```
    Client                    verify_whitespace()
       │                          │
       │  POST /config/verify-     │
       │       whitespace          │
       │  body: {content}          │
       │ ────────────────────────►│
       │                          │  content = data.get("content", "")
       │                          │
       │                          │  if not content:
       │                          │    return {success, issues: [], message}
       │                          │
       │                          │  issues = []
       │                          │  for i, line in enumerate(content.split("\n"), 1):
       │                          │    if "\t" in line:
       │                          │      issues += {line, type: "tab", message}
       │                          │    if line != line.rstrip():
       │                          │      issues += {line, type: "trailing", message}
       │                          │
       │                          │  return {success, issues, has_issues, message}
       │                          │
       │  JSON                     │
       │ ◄───────────────────────│
```

## Inputs

- Body: `{content: string}`

## Outputs

- `{success: true, issues: [{line, type, message}], has_issues: bool, message: string}`
