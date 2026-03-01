# EC2 CloudFormation (Docker-Based)

`cloudformation/scylla-migrator.yaml` — Deploys EC2 with Docker Compose. Spark and web app run in containers.

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         AWS CLOUDFORMATION STACK                                       │
│                                                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Parameters: VpcId, SubnetId, KeyName, InstanceType, RepoUrl, IamInstanceProfile │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                         │                                               │
│  ┌─────────────────────────────────────┼─────────────────────────────────────────────┐  │
│  │ Resources                           ▼                                             │  │
│  │                                                                                    │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐  │  │
│  │  │ IAM Role         │  │ Security Group  │  │ EC2 Instance                     │  │  │
│  │  │ + SSM policy     │  │ Ports: 22,     │  │ AL2023, public IP                │  │  │
│  │  │ (or user-provided│  │ 5000, 8080,    │  │ UserData: bootstrap script       │  │  │
│  │  │  IamProfile)     │  │ 18080, 8081    │  │                                  │  │  │
│  │  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────────┘  │  │
│  │           │                    │                           │                     │  │
│  │           └────────────────────┼───────────────────────────┘                     │  │
│  │                                │                                                │  │
│  └────────────────────────────────┼────────────────────────────────────────────────┘  │
└───────────────────────────────────┼────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         EC2 INSTANCE (UserData Bootstrap)                             │
│                                                                                        │
│   1. yum update, install docker                                                        │
│   2. systemctl start docker                                                           │
│   3. git clone REPO_URL → /home/ec2-user/scylla-migrator                              │
│   4. mkdir data/spark-master, data/spark-worker, data/spark-events                     │
│   5. EXTERNAL_HOST = instance metadata (public-ipv4)                                  │
│   6. docker compose -f docker-compose.ec2.yml up -d                                    │
│   7. sleep 120, post-deploy-wait.sh                                                    │
│                                                                                        │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                    DOCKER COMPOSE (docker-compose.ec2.yml)                             │
│                                                                                        │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐           │
│  │ spark-master        │  │ spark-worker        │  │ web-app             │           │
│  │ (dockerfiles/spark) │  │ (dockerfiles/spark) │  │ (web-app/)          │           │
│  │                     │  │ depends_on: master  │  │ depends_on: master  │           │
│  │ ports: 4040,8080,   │  │ ports: 8081         │  │ ports: 5000         │           │
│  │        18080       │  │                     │  │                     │           │
│  │ volumes: /jars,     │  │ volumes: parquet   │  │ volumes: /app,      │           │
│  │  /app, spark-events │  │                     │  │  /jars, docker.sock  │           │
│  │                     │  │                     │  │ USE_DOCKER_EXEC=1  │           │
│  └──────────┬──────────┘  └──────────┬──────────┘  └──────────┬──────────┘           │
│             │                         │                        │                     │
│             └─────────────────────────┼────────────────────────┘                     │
│                                       │                                               │
│                    scylla-migrator-spark-network (bridge)                             │
│                                                                                        │
│  ┌─────────────────────┐                                                             │
│  │ dynamodb-local       │  (optional local DynamoDB for testing)                        │
│  │ ports: 8001:8000     │                                                             │
│  └─────────────────────┘                                                              │
│                                                                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Request Flow: User → Web App → Spark

```
    Browser                    Web App Container              Spark Master Container
       │                              │                               │
       │  POST /jobs/submit           │                               │
       │ ─────────────────────────►   │                               │
       │                              │  docker exec spark-master     │
       │                              │  spark-submit ...              │
       │                              │ ────────────────────────────► │
       │                              │                               │  runs Migrator
       │                              │  {success, pid: 0}             │  (driver + executors)
       │  ◄─────────────────────────  │ ◄──────────────────────────── │
       │                              │                               │
       │  GET /logs/worker            │  docker logs spark-worker     │
       │ ─────────────────────────►   │ ────────────────────────────► │  (spark-worker container)
       │  ◄─────────────────────────  │ ◄──────────────────────────── │
```

## Outputs

```
InstanceId, PublicIp, WebAppUrl, SparkMasterUrl, SparkHistoryUrl, SshCommand, SsmConnectCommand
```
