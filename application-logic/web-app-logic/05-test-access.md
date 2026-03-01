# test_access() — POST /config/test-access

Rudimentary connectivity checks for source and target (not Spark data validation).

## Flow

```
    Client                    test_access()                  Source/Target Helpers
       │                          │                                    │
       │  POST /config/test-access │                                    │
       │  body: {content}          │                                    │
       │ ────────────────────────►│                                    │
       │                          │  cfg = yaml.safe_load(content)      │
       │                          │  results = {source: {}, target: {}, success}
       │                          │                                    │
       │                          │  ═══════ SOURCE TESTS ═══════       │
       │                          │                                    │
       │                          │  cassandra/scylla:                 │
       │                          │    _test_cql_connect(host,port,...) │
       │                          │ ─────────────────────────────────► │
       │                          │    (ok, msg) ◄─────────────────────│
       │                          │                                    │
       │                          │  parquet:                          │
       │                          │    s3:// path? _test_s3_path_access │
       │                          │    else    _test_parquet_path       │
       │                          │                                    │
       │                          │  dynamodb (AWS):                    │
       │                          │    _test_dynamodb_aws_access        │
       │                          │  dynamodb (Alternator):             │
       │                          │    _test_alternator_connect         │
       │                          │                                    │
       │                          │  dynamodb-s3-export:                │
       │                          │    _test_s3_aws_access              │
       │                          │                                    │
       │                          │  ═══════ TARGET TESTS ═══════       │
       │                          │                                    │
       │                          │  scylla/cassandra:                 │
       │                          │    _test_cql_write(...)             │
       │                          │                                    │
       │                          │  dynamodb/alternator:               │
       │                          │    _test_alternator_connect        │
       │                          │    if ok and table:                │
       │                          │      _test_alternator_table        │
       │                          │    if table not found:              │
       │                          │      _get_source_schema...          │
       │                          │      _build_create_table_cli/payload│
       │                          │      → createTableCommand, payload │
       │                          │                                    │
       │                          │  results.success = all ok          │
       │                          │                                    │
       │  JSON {source, target,   │                                    │
       │        success}          │                                    │
       │ ◄───────────────────────│                                    │
```

## Source Type Routing

```
                    source.type
                         │
    ┌────────────────────┼────────────────────┬────────────────────┐
    │ cassandra          │ parquet             │ dynamodb            │
    │ scylla             │                     │ dynamo              │
    ▼                    ▼                     ▼
 _test_cql_connect   path s3? → S3 test    endpoint host?
                     else → _test_parquet    │
                                            ├─ no/aws → _test_dynamodb_aws_access
                                            └─ yes   → _test_alternator_connect
```

## Target Type Routing

```
                    target.type
                         │
    ┌────────────────────┼────────────────────┐
    │ scylla             │ dynamodb            │
    │ cassandra          │ dynamo              │
    ▼                    ▼
 _test_cql_write     endpoint host?
                     ├─ no  → _test_dynamodb_aws_access
                     └─ yes → _test_alternator_connect
                              └─ if table missing → createTableCommand, payload
```
