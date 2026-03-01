# Web App Logic — Flow Diagrams

Detailed ASCII flow diagrams for each web app route and helper function.

## Routes (by file)

| Function | Route | Method | Description |
|----------|-------|--------|-------------|
| `index` | / | GET | Dashboard with Spark UI links |
| `get_config` | /config | GET | Load config file content |
| `save_config` | /config | POST | Save config, optional validate |
| `parse_config` | /config/parse | POST | Parse YAML → form structure |
| `verify_whitespace` | /config/verify-whitespace | POST | Check tabs, trailing spaces |
| `test_access` | /config/test-access | POST | Test source/target connectivity |
| `execute_create_table` | /config/execute-create-table | POST | Create Alternator table |
| `validate_config_file` | /config/validate | POST | Validate via spark-submit |
| `submit_job` | /jobs/submit | POST | Submit migration job |
| `jobs_status` | /jobs/status | GET | Return Spark UI URLs |
| `network_mapping` | /api/network-mapping | GET | Docker network inspect |
| `worker_logs` | /logs/worker | GET | Worker log tail |
