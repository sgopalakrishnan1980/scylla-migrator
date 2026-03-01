# Application Logic

ASCII diagrams and flow documentation for the Scylla Migrator deployment options and web app.

## Contents

| File | Description |
|------|-------------|
| `web-app-overview.md` | Web app architecture and request flow |
| `ec2-cloudformation-overview.md` | EC2 with Docker (cloudformation/) |
| `ec2-no-docker-overview.md` | EC2 without Docker (ec2-no-docker/) |
| `web-app-logic/` | Detailed flow diagrams for each web app function |

### web-app-logic/

| File | Function | Description |
|------|----------|-------------|
| `01-index.md` | index | Dashboard render |
| `02-get-config.md` | get_config | Load config file |
| `03-parse-config.md` | parse_config | YAML → form structure |
| `04-verify-whitespace.md` | verify_whitespace | Tabs/trailing check |
| `05-test-access.md` | test_access | Source/target connectivity |
| `06-execute-create-table.md` | execute_create_table | Alternator CreateTable |
| `07-validate-config.md` | validate_config_file | spark-submit validate |
| `08-save-config.md` | save_config | Write config file |
| `09-submit-job.md` | submit_job | Submit migration job |
| `10-jobs-status.md` | jobs_status | Spark UI URLs |
| `11-network-mapping.md` | network_mapping | Docker network info |
| `12-worker-logs.md` | worker_logs | Worker log tail |
| `13-helpers.md` | _ui_base_host, _docker_exec, etc. | Internal helpers |
