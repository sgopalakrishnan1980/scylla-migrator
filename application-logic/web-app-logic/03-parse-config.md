# parse_config() — POST /config/parse

Parses uploaded YAML config and returns a form-ready structure for the UI.

## Flow

```
    Client                    parse_config()
       │                          │
       │  POST /config/parse      │
       │  body: {content}          │
       │ ────────────────────────►│
       │                          │  content = data.get("content", "")
       │                          │
       │                          │  if not content:
       │                          │    return 400 "No config content"
       │                          │
       │                          │  cfg = yaml.safe_load(content)
       │                          │  if not dict: return 400
       │                          │
       │                          │  source = cfg["source"]
       │                          │  target = cfg["target"]
       │                          │  savepoints = cfg["savepoints"]
       │                          │
       │                          │  ┌─────────────────────────────────────────┐
       │                          │  │ Map by source type:                      │
       │                          │  │  cassandra → src_host, port, keyspace... │
       │                          │  │  parquet   → parquet_path, region...     │
       │                          │  │  dynamodb  → ddb_src_table, region...    │
       │                          │  │  alternator→ alt_src_endpoint_host...    │
       │                          │  │  dynamodb-s3-export → s3_bucket, etc.    │
       │                          │  └─────────────────────────────────────────┘
       │                          │
       │                          │  ┌─────────────────────────────────────────┐
       │                          │  │ Map by target type:                      │
       │                          │  │  scylla   → tgt_host, keyspace...       │
       │                          │  │  dynamodb → ddb_tgt_table, region...    │
       │                          │  │  alternator → alt_tgt_endpoint_host...   │
       │                          │  └─────────────────────────────────────────┘
       │                          │
       │                          │  form["savepoints_path"] = ...
       │                          │  form["savepoints_interval"] = ...
       │                          │
       │  JSON {success, form,    │
       │        content}           │
       │ ◄───────────────────────│
```

## Inputs

- Body: `{content: string}` (YAML config text)

## Outputs

- `{success: true, content: string, form: {sourceType, targetType, ...}}` or 400
