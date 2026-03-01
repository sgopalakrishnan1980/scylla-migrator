#!/usr/bin/env python3
"""Scylla Migrator sidecar web app - config, monitoring, job management."""

import json
import logging
import os
import socket
import subprocess
from pathlib import Path

import yaml
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for

try:
    import docker as docker_sdk
except ImportError:
    docker_sdk = None

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # 1MB max config

if os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes"):
    app.debug = True
    logging.getLogger().setLevel(logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

CONFIG_PATH = os.environ.get("MIGRATOR_CONFIG_PATH", "/app/config.yaml")
SPARK_MASTER_HOST = os.environ.get("SPARK_MASTER_HOST", "spark-master")
SPARK_HISTORY_PORT = 18080
SPARK_MASTER_PORT = 8080
SPARK_WORKER_PORT = 8081
STANDALONE_MODE = os.environ.get("STANDALONE_MODE", "").lower() in ("1", "true", "yes")
SPARK_NETWORK_FILTER = os.environ.get("SPARK_NETWORK_FILTER", "scylla-migrator")

_ui_host_cache = None
_docker_client = None


def _get_docker_client():
    """Get Docker client via SDK (uses socket). Falls back to None if SDK unavailable."""
    global _docker_client
    if _docker_client is not None:
        return _docker_client
    if not docker_sdk or not Path("/var/run/docker.sock").exists():
        return None
    try:
        _docker_client = docker_sdk.DockerClient(base_url="unix:///var/run/docker.sock")
        _docker_client.ping()
        return _docker_client
    except Exception:
        _docker_client = None
        return None


def _docker_via_cli(container_name: str, cmd: list, detach: bool = False):
    """Fallback: run docker exec via subprocess when SDK unavailable."""
    full_cmd = ["docker", "exec"]
    if detach:
        full_cmd.append("-d")
    full_cmd.extend([container_name] + cmd)
    try:
        if detach:
            proc = subprocess.Popen(full_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return (0, None, None)
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=120)
        return (result.returncode, result.stdout or "", result.stderr or "")
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _docker_exec(container_name: str, cmd: list, detach: bool = False):
    """Run command in container. Uses SDK first, falls back to docker CLI."""
    client = _get_docker_client()
    if client:
        try:
            container = client.containers.get(container_name)
            if detach:
                container.exec_run(cmd, detach=True)
                return (0, None, None)
            result = container.exec_run(cmd, demux=True)
            out, err = result.output or (None, None)
            stdout = (out or b"").decode("utf-8", errors="replace") if out else ""
            stderr = (err or b"").decode("utf-8", errors="replace") if err else ""
            return (result.exit_code or 0, stdout, stderr)
        except Exception:
            pass
    return _docker_via_cli(container_name, cmd, detach)


def _docker_logs(container_name: str, tail: int = 100) -> str | None:
    """Get last N lines of container logs. Uses SDK first, falls back to docker CLI."""
    client = _get_docker_client()
    if client:
        try:
            container = client.containers.get(container_name)
            logs = container.logs(tail=tail, stdout=True, stderr=True)
            return logs.decode("utf-8", errors="replace") if logs else ""
        except Exception:
            pass
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(tail), container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = (result.stdout or "") + (result.stderr or "")
        return out if out else None
    except Exception:
        return None


def _docker_network_gateway():
    """Run docker network inspect to get gateway (host IP on bridge) for UI links."""
    client = _get_docker_client()
    if client:
        try:
            for net in client.networks.list():
                if SPARK_NETWORK_FILTER in (net.name or ""):
                    net.reload()
                    for cfg in (net.attrs.get("IPAM") or {}).get("Config") or []:
                        gw = cfg.get("Gateway")
                        if gw:
                            return gw
        except Exception:
            pass
    try:
        out = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for net in (out.stdout or "").splitlines():
            net = net.strip()
            if SPARK_NETWORK_FILTER not in net:
                continue
            insp = subprocess.run(
                ["docker", "network", "inspect", net, "--format", "{{range .IPAM.Config}}{{.Gateway}}{{end}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if insp.returncode == 0 and insp.stdout and insp.stdout.strip():
                return insp.stdout.strip()
    except Exception:
        pass
    return None


def _ui_base_host():
    """Host for browser-facing URLs (Spark UIs).
    1. EXTERNAL_HOST (EC2 public IP) if set
    2. Gateway from docker network inspect (host on bridge, for local Docker)
    3. Request host (from Host header)
    4. localhost
    """
    global _ui_host_cache
    if _ui_host_cache is not None:
        return _ui_host_cache

    ext = os.environ.get("EXTERNAL_HOST", "").strip()
    if ext:
        _ui_host_cache = ext
        return ext

    gw = _docker_network_gateway()
    if gw:
        _ui_host_cache = gw
        return gw

    if request and request.host:
        h = request.host.split(":")[0]
        if h:
            _ui_host_cache = h
            return h

    _ui_host_cache = "localhost"
    return "localhost"


@app.route("/")
def index():
    """Dashboard with links to Spark UIs (hidden in standalone mode)."""
    base = _ui_base_host()
    return render_template(
        "index.html",
        spark_master_url=f"http://{base}:{SPARK_MASTER_PORT}",
        spark_history_url=f"http://{base}:{SPARK_HISTORY_PORT}",
        spark_worker_url=f"http://{base}:{SPARK_WORKER_PORT}",
        standalone_mode=STANDALONE_MODE,
        config_path=CONFIG_PATH,
    )


@app.route("/config", methods=["GET"])
def get_config():
    """Load current config file."""
    path = request.args.get("path", CONFIG_PATH)
    try:
        with open(path, "r") as f:
            content = f.read()
        return jsonify({"success": True, "content": content, "path": path})
    except FileNotFoundError:
        return jsonify({"success": False, "error": f"Config file not found: {path}"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/config/parse", methods=["POST"])
def parse_config():
    """Parse uploaded YAML config and return form-ready structure for reload."""
    data = request.get_json() or {}
    content = data.get("content", "")

    if not content or not content.strip():
        return jsonify({"success": False, "error": "No config content"}), 400

    try:
        cfg = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return jsonify({"success": False, "error": f"Invalid YAML: {e}"}), 400

    if not isinstance(cfg, dict):
        return jsonify({"success": False, "error": "Config must be a YAML object"}), 400

    form = {}
    source = cfg.get("source") or {}
    target = cfg.get("target") or {}
    savepoints = cfg.get("savepoints") or {}

    src_type = source.get("type", "cassandra")
    tgt_type = target.get("type", "scylla")
    if src_type == "scylla":
        src_type = "cassandra"
    if tgt_type == "dynamodb" and target.get("endpoint"):
        tgt_type = "alternator"

    form["sourceType"] = src_type
    form["targetType"] = tgt_type

    if src_type == "cassandra":
        form["src_host"] = source.get("host", "cassandra-host")
        form["src_port"] = source.get("port", 9042)
        form["src_keyspace"] = source.get("keyspace", "keyspace")
        form["src_table"] = source.get("table", "table")
        form["src_consistency"] = source.get("consistencyLevel", "LOCAL_QUORUM")
        form["src_preserveTimestamps"] = str(source.get("preserveTimestamps", False)).lower()
        creds = source.get("credentials") or {}
        form["src_username"] = creds.get("username", "")
        form["src_password"] = creds.get("password", "")
    elif src_type == "parquet":
        form["parquet_path"] = source.get("path", "")
        form["parquet_region"] = source.get("region", "")
        creds = source.get("credentials") or {}
        form["parquet_accessKey"] = creds.get("accessKey", "")
        form["parquet_secretKey"] = creds.get("secretKey", "")
        assume = creds.get("assumeRole") or {}
        form["parquet_assumeRoleArn"] = assume.get("arn", "")
        form["parquet_sessionName"] = assume.get("sessionName", "")
    elif src_type == "dynamodb":
        ep = source.get("endpoint") or {}
        creds = source.get("credentials") or {}
        assume = creds.get("assumeRole") or {}
        if ep:
            form["sourceType"] = "alternator"
            form["alt_src_endpoint_host"] = ep.get("host", "http://localhost") + (f":{ep.get('port', 8000)}" if ep.get("port") else "")
            form["alt_src_table"] = source.get("table", "")
            form["alt_src_accessKey"] = creds.get("accessKey", "")
            form["alt_src_secretKey"] = creds.get("secretKey", "")
            form["alt_src_assumeRoleArn"] = assume.get("arn", "")
            form["alt_src_sessionName"] = assume.get("sessionName", "")
        else:
            form["ddb_src_table"] = source.get("table", "")
            form["ddb_src_region"] = source.get("region", "us-east-1")
            form["ddb_src_accessKey"] = creds.get("accessKey", "")
            form["ddb_src_secretKey"] = creds.get("secretKey", "")
            form["ddb_src_assumeRoleArn"] = assume.get("arn", "")
            form["ddb_src_sessionName"] = assume.get("sessionName", "")
    elif src_type == "dynamodb-s3-export":
        form["s3_bucket"] = source.get("bucket", "")
        form["s3_manifest"] = source.get("manifestKey", "")
        form["s3_region"] = source.get("region", "")
        td = source.get("tableDescription") or {}
        ad = (td.get("attributeDefinitions") or [{}])[0] or {}
        form["s3_pk_name"] = ad.get("name", "id")
        form["s3_pk_type"] = ad.get("type", "S")
        creds = source.get("credentials") or {}
        form["s3_accessKey"] = creds.get("accessKey", "")
        form["s3_secretKey"] = creds.get("secretKey", "")
        assume = creds.get("assumeRole") or {}
        form["s3_assumeRoleArn"] = assume.get("arn", "")
        form["s3_sessionName"] = assume.get("sessionName", "")

    if tgt_type == "scylla":
        form["tgt_host"] = target.get("host", "scylla-host")
        form["tgt_port"] = target.get("port", 9042)
        form["tgt_keyspace"] = target.get("keyspace", "keyspace")
        form["tgt_table"] = target.get("table", "table")
        form["tgt_consistency"] = target.get("consistencyLevel", "LOCAL_QUORUM")
        form["tgt_stripZeros"] = str(target.get("stripTrailingZerosForDecimals", False)).lower()
        creds = target.get("credentials") or {}
        form["tgt_username"] = creds.get("username", "")
        form["tgt_password"] = creds.get("password", "")
    elif tgt_type == "dynamodb":
        ep = target.get("endpoint") or {}
        creds = target.get("credentials") or {}
        if ep:
            form["targetType"] = "alternator"
            form["alt_tgt_endpoint_host"] = ep.get("host", "http://localhost") + (f":{ep.get('port', 8000)}" if ep.get("port") else "")
            form["alt_tgt_table"] = target.get("table", "")
            form["alt_tgt_accessKey"] = creds.get("accessKey", "")
            form["alt_tgt_secretKey"] = creds.get("secretKey", "")
        else:
            form["ddb_tgt_table"] = target.get("table", "")
            form["ddb_tgt_region"] = target.get("region", "us-east-1")
            form["ddb_tgt_accessKey"] = creds.get("accessKey", "")
            form["ddb_tgt_secretKey"] = creds.get("secretKey", "")
        form["tgt_removeConsumedCapacity"] = str(target.get("removeConsumedCapacity", True)).lower()
        form["alt_tgt_billingMode"] = target.get("billingMode", "PAY_PER_REQUEST")
    elif tgt_type == "alternator":
        ep = target.get("endpoint") or {}
        form["alt_tgt_endpoint_host"] = ep.get("host", "http://localhost") + (f":{ep.get('port', 8000)}" if ep.get("port") else "")
        form["alt_tgt_table"] = target.get("table", "")
        creds = target.get("credentials") or {}
        form["alt_tgt_accessKey"] = creds.get("accessKey", "")
        form["alt_tgt_secretKey"] = creds.get("secretKey", "")
        form["tgt_removeConsumedCapacity"] = str(target.get("removeConsumedCapacity", True)).lower()
        form["alt_tgt_billingMode"] = target.get("billingMode", "PAY_PER_REQUEST")

    form["savepoints_path"] = savepoints.get("path", "/app/savepoints")
    form["savepoints_interval"] = savepoints.get("intervalSeconds", 300)

    return jsonify({"success": True, "content": content, "form": form})


@app.route("/config/verify-whitespace", methods=["POST"])
def verify_whitespace():
    """Check config content for whitespace issues (tabs, leading/trailing spaces)."""
    data = request.get_json() or {}
    content = data.get("content", "")

    if not content:
        return jsonify({"success": True, "issues": [], "message": "No content to verify"})

    issues = []
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        if "\t" in line:
            issues.append({"line": i, "type": "tab", "message": "Contains tab character (use spaces only)"})
        if line != line.rstrip():
            issues.append({"line": i, "type": "trailing", "message": "Trailing whitespace"})

    return jsonify({
        "success": True,
        "issues": issues,
        "has_issues": len(issues) > 0,
        "message": f"Found {len(issues)} whitespace issue(s)" if issues else "No whitespace issues found",
    })


def _test_cql_connect(host: str, port: int, keyspace: str, table: str, username: str = None, password: str = None) -> tuple[bool, str]:
    """Test CQL connectivity and read access."""
    try:
        from cassandra.cluster import Cluster
        from cassandra.auth import PlainTextAuthProvider

        auth = PlainTextAuthProvider(username=username, password=password) if username and password else None
        cluster = Cluster([host], port=port, auth_provider=auth, connect_timeout=10)
        session = cluster.connect()
        session.execute("SELECT * FROM system.local LIMIT 1")  # Connectivity
        if keyspace and table:
            session.execute(f"SELECT * FROM {keyspace}.{table} LIMIT 1")  # Read access
        cluster.shutdown()
        return True, "Connectivity and read access OK"
    except Exception as e:
        return False, str(e)


def _test_cql_write(host: str, port: int, keyspace: str, table: str, username: str = None, password: str = None) -> tuple[bool, str]:
    """Test CQL connectivity and schema access (no actual write)."""
    try:
        from cassandra.cluster import Cluster
        from cassandra.auth import PlainTextAuthProvider

        auth = PlainTextAuthProvider(username=username, password=password) if username and password else None
        cluster = Cluster([host], port=port, auth_provider=auth, connect_timeout=10)
        session = cluster.connect()
        session.execute("SELECT * FROM system.local LIMIT 1")  # Connectivity
        if keyspace:
            try:
                session.execute(f"DESCRIBE KEYSPACE {keyspace}")
            except Exception as e:
                cluster.shutdown()
                return False, f"Keyspace '{keyspace}' not found: {e}"
        cluster.shutdown()
        return True, "Connectivity and schema access OK"
    except Exception as e:
        return False, str(e)


def _test_alternator_connect(url: str) -> tuple[bool, str]:
    """Test Alternator/DynamoDB endpoint via ListTables."""
    try:
        r = requests.post(
            url,
            json={},
            headers={"X-Amz-Target": "DynamoDB_20120810.ListTables", "Content-Type": "application/x-amz-json-1.0"},
            timeout=10,
        )
        if r.status_code in (200, 400):  # 400 can mean auth/region, but connection worked
            return True, "Connectivity OK"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def _test_alternator_table(url: str, table: str) -> tuple[bool, str]:
    """Test Alternator table access via DescribeTable."""
    try:
        r = requests.post(
            url,
            json={"TableName": table},
            headers={"X-Amz-Target": "DynamoDB_20120810.DescribeTable", "Content-Type": "application/x-amz-json-1.0"},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "Table access OK"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def _describe_alternator_table(url: str, table: str) -> tuple[bool, dict | None, str]:
    """Describe Alternator/DynamoDB table. Returns (ok, schema_dict, message)."""
    try:
        r = requests.post(
            url.rstrip("/"),
            json={"TableName": table},
            headers={"X-Amz-Target": "DynamoDB_20120810.DescribeTable", "Content-Type": "application/x-amz-json-1.0"},
            timeout=10,
        )
        if r.status_code != 200:
            return False, None, f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        tbl = data.get("Table", {})
        key_schema = tbl.get("KeySchema", [])
        attr_defs = tbl.get("AttributeDefinitions", [])
        return True, {"KeySchema": key_schema, "AttributeDefinitions": attr_defs}, "OK"
    except Exception as e:
        return False, None, str(e)


def _get_source_schema_for_create_table(cfg: dict) -> dict | None:
    """Get table schema from source config for CreateTable. Returns {AttributeDefinitions, KeySchema} or None."""
    source = cfg.get("source", {})
    src_type = source.get("type", "")

    if src_type == "dynamodb-s3-export":
        td = source.get("tableDescription", {})
        ad = td.get("attributeDefinitions", [])
        ks = td.get("keySchema", [])
        if not ad or not ks:
            return None
        # Convert to DynamoDB API format (PascalCase)
        return {
            "AttributeDefinitions": [{"AttributeName": a["name"], "AttributeType": a["type"]} for a in ad],
            "KeySchema": [{"AttributeName": k["name"], "KeyType": k["type"]} for k in ks],
        }

    if src_type in ("dynamodb", "dynamo"):
        ep = source.get("endpoint", {}) or {}
        host = (ep.get("host") or "").strip()
        port = int(ep.get("port", 8000))
        table = source.get("table", "")
        if not table:
            return None
        base = host if host.startswith("http") else f"http://{host}"
        url = f"{base.rstrip('/')}:{port}" if port else base.rstrip("/")
        ok, schema, _ = _describe_alternator_table(url, table)
        if ok and schema:
            return schema
        # Try AWS DynamoDB if no endpoint
        if not host or "amazonaws.com" in host:
            creds = source.get("credentials", {}) or {}
            assume = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
            region = source.get("region", "us-east-1")
            if creds.get("accessKey") and creds.get("secretKey"):
                ok, _, session = _get_aws_credentials(creds, assume)
                if ok and session:
                    try:
                        import boto3
                        client = session.client("dynamodb", region_name=region)
                        desc = client.describe_table(TableName=table)
                        tbl = desc.get("Table", {})
                        return {
                            "AttributeDefinitions": tbl.get("AttributeDefinitions", []),
                            "KeySchema": tbl.get("KeySchema", []),
                        }
                    except Exception:
                        pass
        return None

    return None


def _build_create_table_payload(table: str, schema: dict, billing_mode: str = "PAY_PER_REQUEST") -> dict:
    """Build DynamoDB CreateTable request payload."""
    payload = {
        "TableName": table,
        "AttributeDefinitions": schema.get("AttributeDefinitions", []),
        "KeySchema": schema.get("KeySchema", []),
        "BillingMode": billing_mode,
    }
    if billing_mode == "PROVISIONED":
        payload["ProvisionedThroughput"] = {"ReadCapacityUnits": 1, "WriteCapacityUnits": 1}
    return payload


def _build_create_table_cli(table: str, schema: dict, endpoint_url: str, billing_mode: str = "PAY_PER_REQUEST") -> str:
    """Build aws dynamodb create-table CLI command."""
    ad = schema.get("AttributeDefinitions", [])
    ks = schema.get("KeySchema", [])
    ad_str = " ".join(f"AttributeName={a['AttributeName']},AttributeType={a['AttributeType']}" for a in ad)
    ks_str = " ".join(f"AttributeName={k['AttributeName']},KeyType={k['KeyType']}" for k in ks)
    parts = [
        "aws dynamodb create-table",
        f"  --table-name {table}",
        f"  --attribute-definitions {ad_str}",
        f"  --key-schema {ks_str}",
        f"  --endpoint-url {endpoint_url}",
    ]
    if billing_mode == "PROVISIONED":
        parts.insert(-1, "  --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=1")
    else:
        parts.insert(-1, f"  --billing-mode {billing_mode}")
    return " \\\n".join(parts)


def _test_tcp(host: str, port: int) -> tuple[bool, str]:
    """Test TCP connectivity."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, int(port)))
        sock.close()
        return True, "TCP connection OK"
    except Exception as e:
        return False, str(e)


def _test_parquet_path(path: str) -> tuple[bool, str]:
    """Test Parquet path access (local only)."""
    if path.startswith("s3a://") or path.startswith("s3://"):
        return False, "S3 path check not supported (run migration to verify)"
    p = Path(path)
    if p.exists():
        return True, "Local path exists"
    return False, f"Path not found: {path}"


def _get_aws_credentials(creds: dict, assume_role: dict = None) -> tuple[bool, str, object]:
    """Resolve AWS credentials, optionally with sessionToken or assumeRole. Returns (ok, message, session)."""
    try:
        import boto3
        from botocore.exceptions import ClientError

        access_key = (creds or {}).get("accessKey", "").strip()
        secret_key = (creds or {}).get("secretKey", "").strip()
        session_token = (creds or {}).get("sessionToken", "").strip()

        if not access_key or not secret_key:
            return False, "Missing accessKey or secretKey in credentials", None

        # Session token (temporary credentials): use directly for validation; tokens refresh every ~15 min
        if session_token:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token,
            )
            return True, "Credentials OK (session token)", session

        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        if assume_role:
            arn = assume_role.get("arn", "").strip()
            session_name = assume_role.get("sessionName") or assume_role.get("session_name") or "scylla-migrator"
            if not arn:
                return False, "assumeRole.arn is required", None
            try:
                sts = session.client("sts")
                resp = sts.assume_role(RoleArn=arn, RoleSessionName=session_name, DurationSeconds=900)
                creds_obj = resp["Credentials"]
                session = boto3.Session(
                    aws_access_key_id=creds_obj["AccessKeyId"],
                    aws_secret_access_key=creds_obj["SecretAccessKey"],
                    aws_session_token=creds_obj["SessionToken"],
                )
            except ClientError as e:
                return False, f"IAM assume role failed: {e.response.get('Error', {}).get('Message', str(e))}", None

        return True, "Credentials OK", session
    except Exception as e:
        return False, str(e), None


def _test_dynamodb_aws_access(region: str, creds: dict, assume_role: dict = None, table: str = None) -> tuple[bool, str]:
    """Test DynamoDB access with IAM credentials (and optional assumeRole)."""
    ok, msg, session = _get_aws_credentials(creds, assume_role)
    if not ok:
        return False, msg
    try:
        import boto3
        from botocore.exceptions import ClientError

        client = session.client("dynamodb", region_name=region or "us-east-1")
        client.list_tables(Limit=1)
        if table:
            client.describe_table(TableName=table)
        return True, "DynamoDB access and IAM credentials OK"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        if code == "AccessDeniedException":
            return False, f"IAM access denied: {msg}"
        if code == "UnrecognizedClientException":
            return False, f"Invalid credentials: {msg}"
        return False, f"DynamoDB error: {msg}"
    except Exception as e:
        return False, str(e)


def _test_s3_aws_access(
    bucket: str, region: str, creds: dict, assume_role: dict = None, manifest_key: str = None
) -> tuple[bool, str]:
    """Test S3 access with IAM credentials (and optional assumeRole)."""
    ok, msg, session = _get_aws_credentials(creds, assume_role)
    if not ok:
        return False, msg
    try:
        import boto3
        from botocore.exceptions import ClientError

        client = session.client("s3", region_name=region or "us-east-1")
        client.head_bucket(Bucket=bucket)
        if manifest_key:
            client.head_object(Bucket=bucket, Key=manifest_key)
        return True, "S3 access and IAM credentials OK"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        if code in ("403", "AccessDenied"):
            return False, f"IAM access denied: {msg}"
        if code == "InvalidAccessKeyId":
            return False, f"Invalid credentials: {msg}"
        return False, f"S3 error: {msg}"
    except Exception as e:
        return False, str(e)


def _test_s3_path_access(path: str, creds: dict, assume_role: dict = None, region: str = None) -> tuple[bool, str]:
    """Test S3 path (s3a://bucket/prefix) access with IAM credentials."""
    path = path.replace("s3a://", "s3://")
    if not path.startswith("s3://"):
        return False, "Not an S3 path"
    parts = path[5:].strip("/").split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    ok, msg, session = _get_aws_credentials(creds, assume_role)
    if not ok:
        return False, msg
    try:
        import boto3
        from botocore.exceptions import ClientError

        client = session.client("s3", region_name=region or "us-east-1")
        client.head_bucket(Bucket=bucket)
        if key:
            client.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=1)
        return True, "S3 path access and IAM credentials OK"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        if code in ("403", "AccessDenied"):
            return False, f"IAM access denied: {msg}"
        return False, f"S3 error: {msg}"
    except Exception as e:
        return False, str(e)


@app.route("/config/test-access", methods=["POST"])
def test_access():
    """Rudimentary endpoint checks: connectivity and basic access to source and target. Not Spark-based data validation."""
    data = request.get_json() or {}
    content = data.get("content", "")

    if not content:
        return jsonify({"success": False, "error": "No config content"}), 400

    try:
        cfg = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return jsonify({"success": False, "error": f"Invalid YAML: {e}"}), 400

    source = cfg.get("source", {})
    target = cfg.get("target", {})
    src_type = source.get("type", "")
    tgt_type = target.get("type", "")

    results = {"source": {}, "target": {}, "success": True}

    # Test source
    if src_type in ("cassandra", "scylla"):
        host = source.get("host", "")
        port = int(source.get("port", 9042))
        keyspace = source.get("keyspace", "")
        table = source.get("table", "")
        creds = source.get("credentials", {}) or {}
        username = creds.get("username") or ""
        password = creds.get("password") or ""

        ok, msg = _test_cql_connect(host, port, keyspace, table, username or None, password or None)
        results["source"] = {"ok": ok, "message": msg, "type": "cql"}
        if not ok:
            results["success"] = False

    elif src_type == "parquet":
        path = source.get("path", "")
        if path.startswith("s3a://") or path.startswith("s3://"):
            creds = source.get("credentials", {}) or {}
            assume_role = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
            region = source.get("region", "us-east-1")
            if creds.get("accessKey") and creds.get("secretKey"):
                ok, msg = _test_s3_path_access(path, creds, assume_role, region)
                results["source"] = {"ok": ok, "message": msg, "type": "parquet"}
                if not ok:
                    results["success"] = False
            else:
                results["source"] = {"ok": True, "message": "S3 Parquet - add credentials to validate IAM access", "type": "parquet"}
        else:
            ok, msg = _test_parquet_path(path)
            results["source"] = {"ok": ok, "message": msg, "type": "parquet"}
            if not ok:
                results["success"] = False

    elif src_type in ("dynamodb", "dynamo"):
        ep = source.get("endpoint", {}) or {}
        host = ep.get("host", "")
        port = int(ep.get("port", 8000))
        creds = source.get("credentials", {}) or {}
        assume_role = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
        region = source.get("region", "us-east-1")
        table = source.get("table", "")

        if not host or "amazonaws.com" in host:
            # AWS DynamoDB: validate IAM credentials and assumeRole
            if creds.get("accessKey") and creds.get("secretKey"):
                ok, msg = _test_dynamodb_aws_access(region, creds, assume_role, table or None)
                results["source"] = {"ok": ok, "message": msg, "type": "dynamodb"}
                if not ok:
                    results["success"] = False
            else:
                results["source"] = {"ok": True, "message": "AWS DynamoDB (using default credentials) - run migration to verify", "type": "dynamodb"}
        else:
            # Alternator: build full URL with port
            base = host if host.startswith("http") else f"http://{host}"
            url = f"{base.rstrip('/')}:{port}" if port else base.rstrip("/")
            ok, msg = _test_alternator_connect(url)
            results["source"] = {"ok": ok, "message": msg, "type": "dynamodb"}
            if not ok:
                results["success"] = False

    elif src_type == "dynamodb-s3-export":
        bucket = source.get("bucket", "")
        manifest_key = source.get("manifestKey", "")
        creds = source.get("credentials", {}) or {}
        assume_role = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
        region = source.get("region", "us-east-1")
        if creds.get("accessKey") and creds.get("secretKey") and bucket:
            ok, msg = _test_s3_aws_access(bucket, region, creds, assume_role, manifest_key or None)
            results["source"] = {"ok": ok, "message": msg, "type": "s3-export"}
            if not ok:
                results["success"] = False
        else:
            results["source"] = {"ok": True, "message": "S3 export - add credentials to validate IAM access", "type": "s3-export"}

    else:
        results["source"] = {"ok": False, "message": f"Unknown source type: {src_type}", "type": "unknown"}
        results["success"] = False

    # Test target
    if tgt_type in ("scylla", "cassandra"):
        host = target.get("host", "")
        port = int(target.get("port", 9042))
        keyspace = target.get("keyspace", "")
        table = target.get("table", "")
        creds = target.get("credentials", {}) or {}
        username = creds.get("username") or ""
        password = creds.get("password") or ""

        ok, msg = _test_cql_write(host, port, keyspace, table, username or None, password or None)
        results["target"] = {"ok": ok, "message": msg, "type": "cql"}
        if not ok:
            results["success"] = False

    elif tgt_type in ("dynamodb", "dynamo"):
        ep = target.get("endpoint") or {}
        host = (ep.get("host") or "").strip()
        port = int(ep.get("port", 8000))
        table = target.get("table", "")
        creds = target.get("credentials", {}) or {}
        assume_role = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
        region = target.get("region", "us-east-1")

        if not host:
            # AWS DynamoDB target (no endpoint): validate IAM credentials
            if creds.get("accessKey") and creds.get("secretKey") and table:
                ok, msg = _test_dynamodb_aws_access(region, creds, assume_role, table)
                results["target"] = {"ok": ok, "message": msg, "type": "dynamodb"}
                if not ok:
                    results["success"] = False
            else:
                results["target"] = {"ok": True, "message": "AWS DynamoDB target - add credentials to validate IAM", "type": "dynamodb"}
        else:
            # Alternator target: build full URL with port (host may be http://scylla-node1, port 8000)
            base = host if host.startswith("http") else f"http://{host}"
            endpoint_url = f"{base.rstrip('/')}:{port}" if port else base.rstrip("/")
            ok, msg = _test_alternator_connect(endpoint_url)
            target_result = {"ok": ok, "message": msg, "type": "dynamodb"}
            if ok and table:
                ok2, msg2 = _test_alternator_table(endpoint_url, table)
                if not ok2:
                    msg = msg2
                    ok = False
                # Table not found: offer CreateTable command (Alternator returns HTTP 400 with
                # "Table: <name> not found" in message)
                is_table_not_found = (
                    "ResourceNotFoundException" in msg
                    or ("Table:" in msg and "not found" in msg.lower())
                    or "not found" in msg.lower()
                    or "does not exist" in msg.lower()
                    or "404" in msg
                )
                if is_table_not_found:
                    billing_mode = (target.get("billingMode") or "PAY_PER_REQUEST").strip()
                    if not billing_mode:
                        billing_mode = "PAY_PER_REQUEST"
                    schema = _get_source_schema_for_create_table(cfg)
                    if schema:
                        target_result["createTableCommand"] = _build_create_table_cli(
                            table, schema, endpoint_url, billing_mode
                        )
                        target_result["createTablePayload"] = _build_create_table_payload(
                            table, schema, billing_mode
                        )
                        target_result["createTableEndpoint"] = endpoint_url
                    else:
                        target_result["tableNotFoundHint"] = (
                            f"Table '{table}' not found. Ensure source credentials are set and run "
                            "'Check Source & Target Endpoints' (session token is for endpoint checks only) to get the Create Table command."
                        )
            target_result["ok"] = ok
            target_result["message"] = msg
            results["target"] = target_result
            if not ok:
                results["success"] = False

    else:
        results["target"] = {"ok": False, "message": f"Unknown target type: {tgt_type}", "type": "unknown"}
        results["success"] = False

    return jsonify(results)


@app.route("/config/execute-create-table", methods=["POST"])
def execute_create_table():
    """Execute CreateTable against Alternator/DynamoDB endpoint (for table-not-found recovery)."""
    data = request.get_json() or {}
    endpoint = (data.get("endpoint") or "").strip()
    payload = data.get("payload", {})

    if not endpoint or not payload:
        return jsonify({"success": False, "error": "Missing endpoint or payload"}), 400

    try:
        r = requests.post(
            endpoint.rstrip("/"),
            json=payload,
            headers={
                "X-Amz-Target": "DynamoDB_20120810.CreateTable",
                "Content-Type": "application/x-amz-json-1.0",
            },
            timeout=30,
        )
        if r.status_code == 200:
            return jsonify({"success": True, "message": f"Table '{payload.get('TableName', '')}' created"})
        return jsonify({"success": False, "error": f"HTTP {r.status_code}: {r.text[:500]}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/config/validate", methods=["POST"])
def validate_config_file():
    """Validate config file structure (migrator --validate-config). Optionally run rudimentary endpoint checks.
    This is not Spark-based data validation between source and target."""
    if STANDALONE_MODE:
        return jsonify({"success": False, "error": "Validate Config requires the full stack (Spark, migrator JAR). Use standalone for config creation only."}), 400
    data = request.get_json() or {}
    path = data.get("path", CONFIG_PATH)
    include_iam = data.get("include_iam_check", True)

    try:
        content = Path(path).read_text()
    except FileNotFoundError:
        return jsonify({"success": False, "error": f"Config file not found: {path}"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    if not content.strip():
        return jsonify({"success": False, "error": "Config file is empty"}), 400

    result = run_validate_config(path, content, include_iam_check=include_iam)
    return jsonify(result)


@app.route("/config", methods=["POST"])
def save_config():
    """Save config. Accepts form data (yaml content) or generated config."""
    data = request.get_json() or {}
    content = data.get("content", "")
    path = data.get("path", CONFIG_PATH)
    validate_only = data.get("validate_only", False)

    if not content:
        return jsonify({"success": False, "error": "Empty config content"}), 400

    if validate_only:
        result = run_validate_config(path, content)
        return jsonify(result)

    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return jsonify({"success": True, "path": path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _run_spark_submit(cmd_extra: list, config_path: str) -> tuple[int, str, str]:
    """Run spark-submit. Uses docker exec spark-master if available, else local."""
    jars_dir = Path("/jars")
    if not jars_dir.exists():
        jars_dir = Path("/app/migrator/target/scala-2.13")
    jar_files = list(jars_dir.glob("*assembly*.jar"))
    if not jar_files:
        raise FileNotFoundError("Migrator JAR not found. Build with: sbt migrator/assembly")

    base_cmd = [
        "spark-submit",
        "--class", "com.scylladb.migrator.Migrator",
        "--master", f"spark://{SPARK_MASTER_HOST}:7077",
        "--conf", f"spark.scylla.config={config_path}",
        str(jar_files[0]),
    ] + cmd_extra

    # Use docker exec when in containerized setup (SDK or CLI)
    if os.environ.get("USE_DOCKER_EXEC") and Path("/var/run/docker.sock").exists():
        res = _docker_exec("spark-master", base_cmd, detach=False)
        if res is not None:
            return res
        raise RuntimeError(
            "Unable to run spark-submit in spark-master container. "
            "Ensure docker socket is mounted and docker CLI is available."
        )

    result = subprocess.run(base_cmd, capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout, result.stderr


def run_validate_config(path: str, content: str, include_iam_check: bool = True) -> dict:
    """Validate config structure via migrator --validate-config. Optionally run rudimentary endpoint checks (not data validation)."""
    import tempfile

    # Use /app for temp file when using docker exec (shared volume with spark-master)
    tmp_dir = Path("/app") if Path("/app").exists() else Path(tempfile.gettempdir())
    tmp_path = tmp_dir / f"_validate_{os.getpid()}.yaml"
    tmp_path.write_text(content)

    try:
        code, out, err = _run_spark_submit(["--validate-config"], str(tmp_path))
        if code != 0:
            return {"success": False, "error": err or out or "Validation failed"}

        result = {"success": True, "message": "Config validation successful"}

        if include_iam_check:
            try:
                cfg = yaml.safe_load(content)
                access_results = _test_access_impl(cfg)
                result["accessCheck"] = access_results
                if not access_results.get("success", True):
                    result["message"] = "Config OK, but endpoint check failed"
                    result["success"] = False
            except Exception as e:
                result["accessCheck"] = {"success": False, "error": str(e)}
                result["message"] = f"Config OK, endpoint check error: {e}"

        return result
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Validation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        tmp_path.unlink(missing_ok=True)


def _test_access_impl(cfg: dict) -> dict:
    """Rudimentary endpoint checks on parsed config. Returns {source, target, success}. Not Spark data validation."""
    source = cfg.get("source", {})
    target = cfg.get("target", {})
    src_type = source.get("type", "")
    tgt_type = target.get("type", "")
    results = {"source": {}, "target": {}, "success": True}

    # Source tests (same logic as test_access)
    if src_type in ("dynamodb", "dynamo"):
        ep = source.get("endpoint", {}) or {}
        host = ep.get("host", "")
        creds = source.get("credentials", {}) or {}
        assume_role = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
        region = source.get("region", "us-east-1")
        table = source.get("table", "")
        if not host or "amazonaws.com" in host:
            if creds.get("accessKey") and creds.get("secretKey"):
                ok, msg = _test_dynamodb_aws_access(region, creds, assume_role, table or None)
                results["source"] = {"ok": ok, "message": msg, "type": "dynamodb"}
                if not ok:
                    results["success"] = False
            else:
                results["source"] = {"ok": True, "message": "AWS DynamoDB (default creds)", "type": "dynamodb"}
        else:
            port = int(ep.get("port", 8000))
            base = host if host.startswith("http") else f"http://{host}"
            url = f"{base.rstrip('/')}:{port}" if port else base.rstrip("/")
            ok, msg = _test_alternator_connect(url)
            results["source"] = {"ok": ok, "message": msg, "type": "dynamodb"}
            if not ok:
                results["success"] = False
    elif src_type == "dynamodb-s3-export":
        bucket = source.get("bucket", "")
        manifest_key = source.get("manifestKey", "")
        creds = source.get("credentials", {}) or {}
        assume_role = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
        region = source.get("region", "us-east-1")
        if creds.get("accessKey") and creds.get("secretKey") and bucket:
            ok, msg = _test_s3_aws_access(bucket, region, creds, assume_role, manifest_key or None)
            results["source"] = {"ok": ok, "message": msg, "type": "s3-export"}
            if not ok:
                results["success"] = False
        else:
            results["source"] = {"ok": True, "message": "S3 export - add credentials to validate IAM", "type": "s3-export"}
    elif src_type == "parquet":
        path = source.get("path", "")
        if path.startswith("s3a://") or path.startswith("s3://"):
            creds = source.get("credentials", {}) or {}
            assume_role = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
            region = source.get("region", "us-east-1")
            if creds.get("accessKey") and creds.get("secretKey"):
                ok, msg = _test_s3_path_access(path, creds, assume_role, region)
                results["source"] = {"ok": ok, "message": msg, "type": "parquet"}
                if not ok:
                    results["success"] = False
            else:
                results["source"] = {"ok": True, "message": "S3 Parquet - add credentials to validate IAM", "type": "parquet"}
        else:
            ok, msg = _test_parquet_path(path)
            results["source"] = {"ok": ok, "message": msg, "type": "parquet"}
            if not ok:
                results["success"] = False

    # Target tests for DynamoDB / Alternator
    if tgt_type in ("dynamodb", "dynamo"):
        ep = target.get("endpoint") or {}
        host = (ep.get("host") or "").strip()
        port = int(ep.get("port", 8000))
        creds = target.get("credentials", {}) or {}
        assume_role = (creds.get("assumeRole") or {}) if isinstance(creds.get("assumeRole"), dict) else None
        region = target.get("region", "us-east-1")
        table = target.get("table", "")
        if not host:
            # AWS DynamoDB target (no endpoint): validate IAM credentials (session token for validation only)
            if creds.get("accessKey") and creds.get("secretKey") and table:
                ok, msg = _test_dynamodb_aws_access(region, creds, assume_role, table)
                results["target"] = {"ok": ok, "message": msg, "type": "dynamodb"}
                if not ok:
                    results["success"] = False
            else:
                results["target"] = {"ok": True, "message": "AWS DynamoDB target", "type": "dynamodb"}
        else:
            # Alternator target: build full URL with port
            base = host if host.startswith("http") else f"http://{host}"
            endpoint_url = f"{base.rstrip('/')}:{port}" if port else base.rstrip("/")
            ok, msg = _test_alternator_connect(endpoint_url)
            target_result = {"ok": ok, "message": msg, "type": "dynamodb"}
            if ok and table:
                ok2, msg2 = _test_alternator_table(endpoint_url, table)
                if not ok2:
                    msg = msg2
                    ok = False
                is_table_not_found = (
                    "ResourceNotFoundException" in msg
                    or ("Table:" in msg and "not found" in msg.lower())
                    or "not found" in msg.lower()
                    or "does not exist" in msg.lower()
                    or "404" in msg
                )
                if is_table_not_found:
                    billing_mode = (target.get("billingMode") or "PAY_PER_REQUEST").strip()
                    if not billing_mode:
                        billing_mode = "PAY_PER_REQUEST"
                    schema = _get_source_schema_for_create_table(cfg)
                    if schema:
                        target_result["createTableCommand"] = _build_create_table_cli(
                            table, schema, endpoint_url, billing_mode
                        )
                        target_result["createTablePayload"] = _build_create_table_payload(
                            table, schema, billing_mode
                        )
                        target_result["createTableEndpoint"] = endpoint_url
                    else:
                        target_result["tableNotFoundHint"] = (
                            f"Table '{table}' not found. Ensure source credentials are set and run "
                            "'Check Source & Target Endpoints' (session token is for endpoint checks only) to get the Create Table command."
                        )
            target_result["ok"] = ok
            target_result["message"] = msg
            results["target"] = target_result
            if not ok:
                results["success"] = False

    return results


@app.route("/jobs/submit", methods=["POST"])
def submit_job():
    """Submit migration job via spark-submit (runs in background)."""
    if STANDALONE_MODE:
        return jsonify({"success": False, "error": "Job submission requires the full stack (Spark). Use standalone for config creation only."}), 400
    data = request.get_json() or {}
    config_path = data.get("config_path", CONFIG_PATH)
    debug = data.get("debug", False)

    if not Path(config_path).exists():
        return jsonify({"success": False, "error": f"Config not found: {config_path}"}), 404

    jars_dir = Path("/jars")
    if not jars_dir.exists():
        jars_dir = Path("/app/migrator/target/scala-2.13")
    jar_files = list(jars_dir.glob("*assembly*.jar"))
    if not jar_files:
        return jsonify({"success": False, "error": "Migrator JAR not found"}), 500

    base_cmd = [
        "spark-submit",
        "--class", "com.scylladb.migrator.Migrator",
        "--master", f"spark://{SPARK_MASTER_HOST}:7077",
        "--conf", "spark.eventLog.enabled=true",
        "--conf", "spark.eventLog.dir=file:/tmp/spark-events",
        "--conf", f"spark.scylla.config={config_path}",
    ]
    if debug:
        log4j_conf = "-Dlog4j2.configurationFile=file:/spark/conf/log4j2-debug.properties"
        base_cmd.extend([
            "--conf", f"spark.driver.extraJavaOptions={log4j_conf}",
            "--conf", f"spark.executor.extraJavaOptions={log4j_conf}",
        ])
    base_cmd.append(str(jar_files[0]))

    if os.environ.get("USE_DOCKER_EXEC") and Path("/var/run/docker.sock").exists():
        res = _docker_exec("spark-master", base_cmd, detach=True)
        if res is not None:
            return jsonify({"success": True, "message": "Job submitted", "pid": 0})
        return jsonify({
            "success": False,
            "error": "Unable to run spark-submit in spark-master. Ensure docker socket is mounted and docker CLI is available.",
        }), 500

    try:
        proc = subprocess.Popen(
            base_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return jsonify({"success": True, "message": "Job submitted", "pid": proc.pid})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/network-mapping")
def network_mapping():
    """Return container→IP mapping from docker network inspect."""
    result = {"networks": {}, "ui_base_host": _ui_base_host()}
    client = _get_docker_client()
    if client:
        try:
            for net in client.networks.list():
                if SPARK_NETWORK_FILTER not in (net.name or ""):
                    continue
                net.reload()
                containers = {}
                for cid, cinfo in (net.attrs.get("Containers") or {}).items():
                    name = cinfo.get("Name", cid[:12])
                    addr = (cinfo.get("IPv4Address") or "").split("/")[0]
                    if addr:
                        containers[name] = addr
                gw = None
                for cfg in (net.attrs.get("IPAM") or {}).get("Config") or []:
                    if cfg.get("Gateway"):
                        gw = cfg["Gateway"]
                        break
                result["networks"][net.name or net.id] = {"containers": containers, "gateway": gw}
            return jsonify({"success": True, **result})
        except Exception:
            pass
    try:
        out = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for net in (out.stdout or "").splitlines():
            net = net.strip()
            if SPARK_NETWORK_FILTER not in net:
                continue
            insp = subprocess.run(
                ["docker", "network", "inspect", net],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if insp.returncode != 0 or not insp.stdout:
                continue
            data = json.loads(insp.stdout)
            for item in data if isinstance(data, list) else [data]:
                containers = {}
                for cid, cinfo in (item.get("Containers") or {}).items():
                    name = cinfo.get("Name", cid[:12])
                    addr = (cinfo.get("IPv4Address") or "").split("/")[0]
                    if addr:
                        containers[name] = addr
                gw = None
                for cfg in (item.get("IPAM") or {}).get("Config") or []:
                    if cfg.get("Gateway"):
                        gw = cfg["Gateway"]
                        break
                result["networks"][net] = {"containers": containers, "gateway": gw}
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/jobs/status")
def jobs_status():
    """Return link to Spark History Server for job status."""
    base = _ui_base_host()
    return jsonify({
        "history_url": f"http://{base}:{SPARK_HISTORY_PORT}",
        "master_url": f"http://{base}:{SPARK_MASTER_PORT}",
        "worker_url": f"http://{base}:{SPARK_WORKER_PORT}",
    })


@app.route("/logs/worker")
def worker_logs():
    """Stream worker logs - returns last N lines via docker logs or file tail."""
    lines = int(request.args.get("lines", 100))
    content = _docker_logs("spark-worker", tail=lines)
    if content:
        return jsonify({"success": True, "content": content, "source": "docker logs"})
    # Fallback: look for log files (when web-app runs inside spark-master)
    import glob
    for pattern in ["/tmp/spark-*/logs/*.out", "/spark/logs/*.out"]:
        for f in glob.glob(pattern):
            try:
                content = "".join(Path(f).read_text().splitlines(keepends=True)[-lines:])
                return jsonify({"success": True, "content": content, "source": f})
            except Exception:
                pass
    return jsonify({"success": False, "error": "Worker logs not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
