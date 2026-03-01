# get_config() — GET /config

Loads and returns the current config file content.

## Flow

```
    Client                    get_config()
       │                          │
       │  GET /config?path=X       │
       │ ────────────────────────►│
       │                          │  path = request.args.get("path", CONFIG_PATH)
       │                          │
       │                          │  try:
       │                          │    content = open(path).read()
       │                          │    return {success, content, path}
       │                          │  except FileNotFoundError:
       │                          │    return 404
       │                          │  except Exception:
       │                          │    return 500
       │                          │
       │  JSON                     │
       │ ◄───────────────────────│
```

## Inputs

- Query: `path` (optional, defaults to MIGRATOR_CONFIG_PATH)

## Outputs

- `{success: true, content: string, path: string}` or error
