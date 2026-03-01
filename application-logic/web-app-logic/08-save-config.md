# save_config() — POST /config

Saves config content to file. Optionally validates before saving.

## Flow

```
    Client                    save_config()
       │                          │
       │  POST /config            │
       │  body: {content, path,   │
       │         validate_only}   │
       │ ────────────────────────►│
       │                          │  content = data.get("content", "")
       │                          │  path = data.get("path", CONFIG_PATH)
       │                          │  validate_only = data.get("validate_only", False)
       │                          │
       │                          │  if validate_only:
       │                          │    result = run_validate_config(...)
       │                          │    return jsonify(result)
       │                          │    (no file write)
       │                          │
       │                          │  try:
       │                          │    with open(path, "w") as f:
       │                          │      f.write(content)
       │                          │    return {success: true, path}
       │                          │  except Exception:
       │                          │    return 500 {error}
       │                          │
       │  JSON                     │
       │ ◄───────────────────────│
```

## Inputs

- Body: `{content: string, path?: string, validate_only?: boolean}`

## Outputs

- `{success: true, path: string}` or validation result if validate_only
