# EC2 CloudFormation (No Docker)

`ec2-no-docker/cloudformation.yaml` — Deploys EC2 with native Spark binaries and Flask. No Docker.

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         AWS CLOUDFORMATION STACK                                       │
│                                                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Parameters: VpcId, SubnetId, KeyName, InstanceType, RepoUrl,                     │  │
│  │              PrebuiltJarBucket, PrebuiltJarKey (optional)                         │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                         │                                               │
│  ┌─────────────────────────────────────┼─────────────────────────────────────────────┐  │
│  │ Resources                           ▼                                             │  │
│  │                                                                                    │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐  │  │
│  │  │ IAM Role        │  │ Security Group  │  │ EC2 Instance                     │  │  │
│  │  │ SSM only        │  │ Ports: 22,     │  │ AL2023, public IP                │  │  │
│  │  │ (+ S3 policy    │  │ 5000, 8080,    │  │ UserData: full bootstrap         │  │  │
│  │  │  if PrebuiltJar)│  │ 18080, 8081   │  │   (no Docker)                     │  │  │
│  │  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────────┘  │  │
│  └───────────┼────────────────────┼──────────────────────────┘                     │  │
└──────────────┼────────────────────┼────────────────────────────────────────────────┘
               │                    │
               ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         EC2 INSTANCE (UserData Bootstrap)                             │
│                                                                                        │
│  PHASE 1: System packages                                                              │
│    dnf install java-11-amazon-corretto-headless python3 python3-pip git wget tar       │
│                                                                                        │
│  PHASE 2: Spark 3.5.8 (bin-hadoop3-scala2.13)                                         │
│    wget → /tmp/spark-*.tgz                                                            │
│    tar -xzf → /opt/spark                                                              │
│    SPARK_HOME=/opt/spark                                                               │
│                                                                                        │
│  PHASE 3: Start Spark (native, no containers)                                          │
│    start-master.sh          → background                                               │
│    start-worker.sh spark://localhost:7077  → background                                │
│    start-history-server.sh  → background                                               │
│                                                                                        │
│  PHASE 4: scylla-migrator                                                              │
│    git clone → /home/ec2-user/scylla-migrator                                          │
│    JAR: PrebuiltJarBucket/Key → S3 cp  OR  sbt migrator/assembly (coursier)           │
│                                                                                        │
│  PHASE 5: Flask web app                                                                │
│    pip install flask requests PyYAML cassandra-driver boto3                             │
│    Symlinks: /app → repo, /jars → migrator/target, /spark → /opt/spark                │
│    systemd: scylla-migrator-web.service (python3 -m flask run --host=0.0.0.0)         │
│    No USE_DOCKER_EXEC → spark-submit runs via subprocess on host                       │
│                                                                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Single-Host Layout (No Docker)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         EC2 HOST (Amazon Linux 2023)                                   │
│                                                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │ /opt/spark                                                                        │  │
│  │   sbin/start-master.sh  ──►  Master JVM (port 7077, UI 8080)                     │  │
│  │   sbin/start-worker.sh ──►  Worker JVM (port 8081)                               │  │
│  │   sbin/start-history  ──►  History Server (port 18080)                           │  │
│  │   bin/spark-submit     ──►  Used by web app to launch jobs                       │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │ systemd: scylla-migrator-web.service (ec2-user)                                   │  │
│  │   SPARK_MASTER_HOST=localhost                                                     │  │
│  │   MIGRATOR_CONFIG_PATH=/home/ec2-user/scylla-migrator/config.yaml                  │  │
│  │   python3 -m flask run --host=0.0.0.0 --port=5000                                 │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                                 │
│  │ /app         │  │ /jars        │  │ /spark       │   (symlinks)                    │
│  │ → repo       │  │ → target/...  │  │ → /opt/spark │                                 │
│  └──────────────┘  └──────────────┘  └──────────────┘                                 │
│                                                                                        │
│  /tmp/spark-events   (event log for History Server)                                     │
│                                                                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Comparison: EC2 Docker vs EC2 No-Docker

```
┌──────────────────────────────┬──────────────────────────────┬──────────────────────────────┐
│         EC2 (Docker)         │      EC2 (No Docker)         │                              │
├──────────────────────────────┼──────────────────────────────┼──────────────────────────────┤
│ cloudformation/               │ ec2-no-docker/               │                              │
├──────────────────────────────┼──────────────────────────────┼──────────────────────────────┤
│ Docker + Compose              │ No Docker                    │                              │
│ 3 containers: master, worker,│ Single host: Spark processes │                              │
│ web-app (+ dynamodb-local)    │ + Flask systemd service      │                              │
├──────────────────────────────┼──────────────────────────────┼──────────────────────────────┤
│ USE_DOCKER_EXEC=1             │ USE_DOCKER_EXEC unset       │                              │
│ spark-submit via docker exec  │ spark-submit via subprocess  │                              │
│ spark-master                  │ on host                     │                              │
├──────────────────────────────┼──────────────────────────────┼──────────────────────────────┤
│ JAR: build before EC2 or      │ JAR: sbt on EC2 or           │                              │
│ mount/copy into container     │ PrebuiltJarBucket/Key        │                              │
├──────────────────────────────┼──────────────────────────────┼──────────────────────────────┤
│ Worker logs: docker logs      │ Worker logs: file tail       │                              │
│ spark-worker                  │ /spark/logs/*.out            │                              │
└──────────────────────────────┴──────────────────────────────┴──────────────────────────────┘
```
