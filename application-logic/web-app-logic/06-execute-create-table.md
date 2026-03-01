# execute_create_table() — POST /config/execute-create-table

Executes CreateTable against an Alternator/DynamoDB endpoint (table-not-found recovery).

## Flow

```
    Client                    execute_create_table()           Alternator Endpoint
       │                          │                                    │
       │  POST /config/execute-    │                                    │
       │       create-table        │                                    │
       │  body: {endpoint,         │                                    │
       │         payload}          │                                    │
       │ ────────────────────────►│                                    │
       │                          │  endpoint = data.get("endpoint")    │
       │                          │  payload = data.get("payload")      │
       │                          │                                    │
       │                          │  if not endpoint or not payload:    │
       │                          │    return 400                       │
       │                          │                                    │
       │                          │  requests.post(                     │
       │                          │    endpoint,                        │
       │                          │    json=payload,                    │
       │                          │    headers={                        │
       │                          │      "X-Amz-Target":                │
       │                          │        "DynamoDB_20120810.CreateTable",
       │                          │      "Content-Type":                │
       │                          │        "application/x-amz-json-1.0" │
       │                          │    }                               │
       │                          │  )                                 │
       │                          │ ──────────────────────────────────► │
       │                          │                                    │
       │                          │  if status 200:                     │
       │                          │    return {success, message}       │
       │                          │  else:                             │
       │                          │    return 400 {error}              │
       │                          │ ◄─────────────────────────────────│
       │                          │                                    │
       │  JSON                     │                                    │
       │ ◄───────────────────────│                                    │
```

## Payload Origin

- Payload is built by `_build_create_table_payload()` in test_access when target table is not found.
- Uses source schema (from DynamoDB/Alternator DescribeTable or S3 manifest) to generate AttributeDefinitions, KeySchema.
