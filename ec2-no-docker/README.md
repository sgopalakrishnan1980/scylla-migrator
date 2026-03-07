# Scylla Migrator - EC2 without Docker

Deploys a single Amazon Linux EC2 instance with **SSM** (Session Manager), **Apache Spark 3.5.8 Standalone** (with Hadoop 3, Scala 2.13), **Spark Connect**, and the **Python Flask web app**. No Docker—everything runs natively via systemd services under `ec2-user`.

## What gets installed

| Component           | Version / details                                      |
|---------------------|---------------------------------------------------------|
| Amazon Linux        | AL2023 (latest AMI)                                    |
| Spark               | 3.5.8 (bin-hadoop3-scala2.13) from [Apache archive](https://archive.apache.org/dist/spark/) |
| Spark Standalone    | Master (7077, UI 8080), Worker (8081), History (18080), Connect (15002). Reverse proxy enabled. |
| systemd services    | spark-master, spark-worker, spark-history-server, spark-connect-server, scylla-migrator-web |
| Install location    | `/home/ec2-user/` — Spark, web-app, and repo all under ec2-user home |
| pyenv               | Python 3.11 (in `/home/ec2-user/.pyenv`)              |
| PySpark + deps      | flask, requests, PyYAML, cassandra-driver, boto3, scylla-cqlsh, scylla-driver |
| Tools               | AWS CLI v2, cassandra-stress (3.17.0), scylla-bench (1.0.0) |
| Migrator JAR        | Built with sbt from repo, or provided via S3           |

## Instance profile & connectivity

### SSM agent for connectivity

The instance uses **AWS Systems Manager Session Manager (SSM)** for access—no SSH key or bastion host required. Ideal for instances in private subnets.

- **Managed policy:** `AmazonSSMManagedInstanceCore` — enables SSM agent and Session Manager
- **Connect:**
  ```bash
  aws ssm start-session --target <instance-id>
  ```
- The CloudFormation output `SsmConnectCommand` provides the full command.

### DynamoDB access for source connections

The instance profile includes **full DynamoDB access** so the migrator can connect to DynamoDB sources and run migrations from DynamoDB to Scylla Alternator.

- **Policy:** `MigratorRoleDynamoDBPolicy` — `dynamodb:*` on `*`
- No additional IAM setup needed for DynamoDB-based migrations.

### S3 access (optional)

When `PrebuiltJarBucket` and `PrebuiltJarKey` are set, the instance gets S3 read access for the specified bucket to download the pre-built migrator JAR.

## Prerequisites

- AWS CLI configured
- VPC and subnet with internet access
- SSH key pair in the target region (for EC2; SSM does not require it)
- (Optional) Pre-built migrator JAR in S3 for faster bootstrap

## Deploy

```bash
aws cloudformation create-stack \
  --stack-name scylla-migrator-no-docker \
  --template-body file://cloudformation.yaml \
  --parameters \
    ParameterKey=VpcId,ParameterValue=vpc-xxxxx \
    ParameterKey=SubnetId,ParameterValue=subnet-xxxxx \
    ParameterKey=KeyName,ParameterValue=your-keypair
```

### Parameters

| Parameter          | Default                                | Description                                      |
|--------------------|----------------------------------------|--------------------------------------------------|
| VpcId              | (required)                             | VPC for the instance                             |
| SubnetId           | (required)                             | Subnet in the VPC                                |
| KeyName            | (required)                             | EC2 key pair                                    |
| InstanceType       | m6i.4xlarge                            | Instance size (m6i/c6i variants)                 |
| VpcCidrBlock       | 10.0.0.0/16                            | VPC CIDR for security group rules                |
| AllowedCidr        | 0.0.0.0/0                              | CIDR allowed for web app and Spark UIs          |
| RepoUrl            | github.com/sgopalakrishnan1980/scylla-migrator | Git repo (must include web-app/)        |
| PrebuiltJarBucket  | ''                                     | Optional S3 bucket for pre-built migrator JAR   |
| PrebuiltJarKey     | ''                                     | Optional S3 key for pre-built migrator JAR      |

### Faster bootstrap with pre-built JAR

To skip the sbt build (5–15 minutes), build the JAR locally and upload to S3:

```bash
sbt migrator/assembly
aws s3 cp migrator/target/scala-2.13/migrator-assembly.jar s3://your-bucket/migrator/migrator-assembly.jar
```

Then set `PrebuiltJarBucket` and `PrebuiltJarKey` when creating the stack.

## After deployment

Bootstrap typically takes 5–20 minutes (longer if building from source). Check user-data progress:

```bash
aws ssm start-session --target <instance-id>
sudo tail -f /var/log/user-data.log
```

### CloudFormation outputs

The stack exposes clickable URLs:

| Output          | Description                          |
|-----------------|--------------------------------------|
| WebAppUrl       | Web app (Flask UI) — http://\<ip\>:5000 |
| SparkMasterUrl  | Spark Master UI — http://\<ip\>:8080 |
| SparkHistoryUrl | Spark History Server — http://\<ip\>:18080 |
| SparkConnectUrl | Spark Connect endpoint — sc://\<ip\>:15002 |
| SsmConnectCommand | `aws ssm start-session --target <instance-id>` |
| SshCommand      | SSH command (if using public IP)     |

### Connect via SSM (recommended)

```bash
aws ssm start-session --target <instance-id>
```

### Service management

All services run as `ec2-user`. You can manage them with:

```bash
sudo systemctl start scylla-migrator-web
sudo systemctl restart spark-master
# etc.
```

ec2-user has passwordless sudo for these service operations.

| Service                | Unit name                    |
|------------------------|------------------------------|
| Web app                | scylla-migrator-web.service  |
| Spark Master           | spark-master.service         |
| Spark Worker           | spark-worker.service         |
| Spark History Server   | spark-history-server.service |
| Spark Connect Server   | spark-connect-server.service |

### URLs (replace `<public-ip>` with the instance public IP)

| Service        | URL                        |
|----------------|----------------------------|
| Web app        | http://\<public-ip\>:5000  |
| Spark Master   | http://\<public-ip\>:8080  |
| Spark History  | http://\<public-ip\>:18080 |
| Spark Worker   | http://\<public-ip\>:8081  |
| Spark Connect  | sc://\<public-ip\>:15002   |

### Config

Edit `/home/ec2-user/scylla-migrator/config.yaml` with your source and target settings.

### Spark reverse proxy and external host

Spark is configured for access via the instance’s public hostname:

- **spark.ui.reverseProxy** — `true` on Master, Worker, and History Server
- **spark.master.rest.host** — Set to the external host (Public DNS or IP)
- **spark.history.ui.reverseProxyUrl** — `http://<host>:18080`
- **SPARK_PUBLIC_DNS** — Set for all Spark daemons so worker UIs use the correct host

These values are stored in `/etc/scylla-migrator-spark.env` and loaded by the Spark systemd services.

### Delayed host update (~120 seconds)

Public DNS may not be available immediately at bootstrap. A background job runs ~120 seconds after launch and:

1. Fetches the instance’s Public DNS (or Public IP) via AWS EC2 API
2. Updates `/etc/scylla-migrator.env` (EXTERNAL_HOST)
3. Updates `/etc/scylla-migrator-spark.env` with the same host for Spark config
4. Updates `scylla-migrator-web.service` with the new EXTERNAL_HOST
5. Restarts the web app and all Spark daemons (master, worker, history server, connect server)

Log output: `/var/log/external-host-update.log`

### Troubleshooting

- **User-data / bootstrap:** `/var/log/user-data.log`, `/var/log/cloud-init-output.log`
- **Service status:** `sudo systemctl status scylla-migrator-web`
- **Service logs:** `sudo journalctl -u scylla-migrator-web -n 100`
- **Web app not starting:** Ensure `RepoUrl` points to a repo that contains a `web-app/` directory; otherwise the service is skipped.
