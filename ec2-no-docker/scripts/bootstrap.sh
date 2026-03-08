#!/bin/bash
# Scylla Migrator EC2 bootstrap: Spark, Livy, pyenv, web app. Invoked by UserData.
set -e

SPARK_VERSION="${SPARK_VERSION:-3.5.8}"
SPARK_URL="${SPARK_URL:-https://archive.apache.org/dist/spark/spark-3.5.8/spark-3.5.8-bin-hadoop3-scala2.13.tgz}"
SPARK_HOME="${SPARK_HOME:-/home/ec2-user/spark}"
SPARK_EVENTS="${SPARK_EVENTS:-/home/ec2-user/spark-events}"
SPARK_PID_DIR="${SPARK_PID_DIR:-/home/ec2-user/spark-pids}"
REPO_URL="${REPO_URL:-}"
DEPLOY_DIR="${DEPLOY_DIR:-/home/ec2-user/scylla-migrator}"
PREBUILT_BUCKET="${PREBUILT_BUCKET:-}"
PREBUILT_KEY="${PREBUILT_KEY:-}"

LIVY_VERSION="0.8.0-incubating"
LIVY_SCALA="2.12"
LIVY_URL="https://archive.apache.org/dist/incubator/livy/${LIVY_VERSION}/apache-livy-${LIVY_VERSION}_${LIVY_SCALA}-bin.zip"
LIVY_HOME="${LIVY_HOME:-/opt/livy}"

echo "=== Scylla Migrator EC2 - Spark Standalone + Livy + Connect + pyenv ==="

mkdir -p /home/ec2-user
chown -R ec2-user:ec2-user /home/ec2-user 2>/dev/null || true

dnf update -y
dnf install -y java-17-amazon-corretto-headless git wget tar gzip unzip which make gcc patch zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel openssl-devel tk-devel libffi-devel xz-devel
alternatives --set java /usr/lib/jvm/java-17-amazon-corretto.x86_64/jre/bin/java 2>/dev/null || alternatives --set java /usr/lib/jvm/java-17-amazon-corretto.x86_64/bin/java 2>/dev/null || true

curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q -o /tmp/awscliv2.zip -d /tmp && /tmp/aws/install -i /opt/aws-cli -b /usr/local/bin 2>/dev/null || true
rm -rf /tmp/awscliv2.zip /tmp/aws
aws --version 2>/dev/null || true

wget -q "$SPARK_URL" -O /tmp/spark.tgz
tar -xzf /tmp/spark.tgz -C /tmp
mv /tmp/spark-3.5.8-bin-hadoop3-scala2.13 "$SPARK_HOME"
rm /tmp/spark.tgz
wget -q "https://repo1.maven.org/maven2/org/apache/spark/spark-connect_2.13/3.5.8/spark-connect_2.13-3.5.8.jar" -O "$SPARK_HOME/jars/spark-connect_2.13-3.5.8.jar" 2>/dev/null || true
mkdir -p "$SPARK_EVENTS" "$SPARK_PID_DIR"
chown -R ec2-user:ec2-user "$SPARK_HOME" "$SPARK_EVENTS" "$SPARK_PID_DIR"

sleep 120
INST_ID=""; REG=""
for _ in 1 2 3; do
  TOKEN=$(curl -sf -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" -m 5 2>/dev/null) || true
  if [ -n "$TOKEN" ]; then
    INST_ID=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/instance-id" -m 5 2>/dev/null) || true
    REG=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/placement/region" -m 5 2>/dev/null) || true
  fi
  [ -n "$INST_ID" ] && [ -n "$REG" ] && break
  sleep 10
done
EXTERNAL_HOST=""
for i in 1 2 3; do
  [ -z "$INST_ID" ] || [ -z "$REG" ] && break
  EXTERNAL_HOST=$(aws ec2 describe-instances --instance-ids "$INST_ID" --query "Reservations[0].Instances[0].NetworkInterfaces[0].Association.PublicDnsName" --output text --region "$REG" 2>/dev/null) || true
  [ -z "$EXTERNAL_HOST" ] || [ "$EXTERNAL_HOST" = "None" ] && EXTERNAL_HOST=$(aws ec2 describe-instances --instance-ids "$INST_ID" --query "Reservations[0].Instances[0].PublicDnsName" --output text --region "$REG" 2>/dev/null) || true
  [ -z "$EXTERNAL_HOST" ] || [ "$EXTERNAL_HOST" = "None" ] && EXTERNAL_HOST=$(aws ec2 describe-instances --instance-ids "$INST_ID" --query "Reservations[0].Instances[0].PublicIpAddress" --output text --region "$REG" 2>/dev/null) || true
  [ -n "$EXTERNAL_HOST" ] && [ "$EXTERNAL_HOST" != "None" ] && break
  [ "$i" -lt 3 ] 2>/dev/null && sleep 60
done
if [ -z "$EXTERNAL_HOST" ] || [ "$EXTERNAL_HOST" = "None" ]; then
  echo "WARNING: Metadata discovery for PublicDNS name failed. Proceeding with Spark master and web app setup. Use instance public IP for URLs."
fi
export SPARK_PUBLIC_DNS="$EXTERNAL_HOST"
echo "EXTERNAL_HOST=$EXTERNAL_HOST" | sudo tee /etc/scylla-migrator.env
{ echo "SPARK_PUBLIC_DNS=$EXTERNAL_HOST"; echo "SPARK_MASTER_OPTS=-Dspark.ui.reverseProxy=true -Dspark.master.rest.host=$EXTERNAL_HOST"; echo "SPARK_WORKER_OPTS=-Dspark.ui.reverseProxy=true"; echo "SPARK_HISTORY_OPTS=-Dspark.history.ui.bindAddress=0.0.0.0 -Dspark.history.fs.logDirectory=file:/home/ec2-user/spark-events -Dspark.ui.reverseProxy=true -Dspark.history.ui.reverseProxyUrl=http://$EXTERNAL_HOST:18080"; } | sudo tee /etc/scylla-migrator-spark.env

cat > /etc/systemd/system/spark-master.service << 'SVCEOF'
[Unit]
Description=Spark Standalone Master
After=network.target
Wants=network.target

[Service]
Type=simple
User=ec2-user
Group=ec2-user
TimeoutStartSec=300
EnvironmentFile=-/etc/scylla-migrator-spark.env
Environment="JAVA_HOME=/usr/lib/jvm/java-17-amazon-corretto.x86_64"
Environment="SPARK_HOME=/home/ec2-user/spark"
Environment="SPARK_PID_DIR=/home/ec2-user/spark-pids"
ExecStart=/home/ec2-user/spark/bin/spark-class org.apache.spark.deploy.master.Master --host 0.0.0.0 --port 7077 --webui-port 8080
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/spark-worker.service << 'SVCEOF'
[Unit]
Description=Spark Standalone Worker
After=spark-master.service network.target
Requires=spark-master.service

[Service]
Type=simple
User=ec2-user
Group=ec2-user
TimeoutStartSec=300
EnvironmentFile=-/etc/scylla-migrator-spark.env
Environment="JAVA_HOME=/usr/lib/jvm/java-17-amazon-corretto.x86_64"
Environment="SPARK_HOME=/home/ec2-user/spark"
Environment="SPARK_PID_DIR=/home/ec2-user/spark-pids"
ExecStart=/home/ec2-user/spark/bin/spark-class org.apache.spark.deploy.worker.Worker spark://localhost:7077 --host 0.0.0.0 --webui-port 8081
Restart=on-failure
RestartSec=10
ExecStartPost=/bin/bash -c 'sleep 15 && /bin/systemctl start livy.service || true'

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/spark-history-server.service << 'SVCEOF'
[Unit]
Description=Spark History Server
After=spark-master.service network.target
Requires=spark-master.service

[Service]
Type=simple
User=ec2-user
Group=ec2-user
EnvironmentFile=-/etc/scylla-migrator-spark.env
Environment="JAVA_HOME=/usr/lib/jvm/java-17-amazon-corretto.x86_64"
Environment="SPARK_HOME=/home/ec2-user/spark"
ExecStart=/home/ec2-user/spark/sbin/spark-class org.apache.spark.deploy.history.HistoryServer
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/spark-connect-server.service << 'SVCEOF'
[Unit]
Description=Spark Connect Server
After=spark-worker.service network.target
Requires=spark-worker.service

[Service]
Type=simple
User=ec2-user
Group=ec2-user
EnvironmentFile=-/etc/scylla-migrator-spark.env
Environment="JAVA_HOME=/usr/lib/jvm/java-17-amazon-corretto.x86_64"
Environment="SPARK_HOME=/home/ec2-user/spark"
ExecStart=/home/ec2-user/spark/sbin/start-connect-server.sh --master spark://localhost:7077 --jars /home/ec2-user/spark/jars/spark-connect_2.13-3.5.8.jar
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

# Apache Livy: depends on Spark master and worker; restarts with worker (ExecStartPost in worker starts Livy)
mkdir -p "$(dirname "$LIVY_HOME")"
wget -q "$LIVY_URL" -O /tmp/livy.zip
unzip -q -o /tmp/livy.zip -d /tmp
mv "/tmp/apache-livy-${LIVY_VERSION}_${LIVY_SCALA}-bin" "$LIVY_HOME"
rm /tmp/livy.zip
mkdir -p "$LIVY_HOME/logs" "$LIVY_HOME/run"
[ -f "$LIVY_HOME/conf/livy.conf.template" ] && [ ! -f "$LIVY_HOME/conf/livy.conf" ] && cp "$LIVY_HOME/conf/livy.conf.template" "$LIVY_HOME/conf/livy.conf"
touch "$LIVY_HOME/conf/livy.conf"
chmod +x "$LIVY_HOME/bin/livy-server" 2>/dev/null || true
cat >> "$LIVY_HOME/conf/livy.conf" << LIVYCONF

# Spark Standalone
livy.spark.master = spark://localhost:7077
livy.spark.deploy-mode = cluster
livy.server.port = 8998
livy.server.host = 0.0.0.0
LIVYCONF
chown -R ec2-user:ec2-user "$LIVY_HOME"

cat > /etc/systemd/system/livy.service << 'SVCEOF'
[Unit]
Description=Apache Livy Server
After=spark-worker.service network.target
Requires=spark-master.service spark-worker.service
BindsTo=spark-worker.service

[Service]
Type=simple
User=ec2-user
Group=ec2-user
WorkingDirectory=/opt/livy
Environment="JAVA_HOME=/usr/lib/jvm/java-17-amazon-corretto.x86_64"
Environment="SPARK_HOME=/home/ec2-user/spark"
Environment="LIVY_HOME=/opt/livy"
Environment="LIVY_CONF_DIR=/opt/livy/conf"
Environment="LIVY_PID_DIR=/opt/livy/run"
TimeoutStartSec=120
ExecStart=/opt/livy/bin/livy-server
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

echo 'ec2-user ALL=(ALL) NOPASSWD: /bin/systemctl start spark-master.service, /bin/systemctl stop spark-master.service, /bin/systemctl restart spark-master.service, /bin/systemctl start spark-worker.service, /bin/systemctl stop spark-worker.service, /bin/systemctl restart spark-worker.service, /bin/systemctl start spark-history-server.service, /bin/systemctl stop spark-history-server.service, /bin/systemctl restart spark-history-server.service, /bin/systemctl start spark-connect-server.service, /bin/systemctl stop spark-connect-server.service, /bin/systemctl restart spark-connect-server.service, /bin/systemctl start livy.service, /bin/systemctl stop livy.service, /bin/systemctl restart livy.service, /bin/systemctl start scylla-migrator-web.service, /bin/systemctl stop scylla-migrator-web.service, /bin/systemctl restart scylla-migrator-web.service' > /etc/sudoers.d/scylla-migrator
chmod 440 /etc/sudoers.d/scylla-migrator

sudo systemctl daemon-reload
sudo systemctl enable spark-master.service
sudo systemctl start spark-master.service || { echo "WARNING: spark-master start failed."; }
sleep 20
sudo systemctl enable spark-worker.service
sudo systemctl start spark-worker.service || { echo "WARNING: spark-worker start failed or timed out; run 'sudo systemctl start spark-worker.service' after bootstrap."; }
sleep 5
sudo systemctl enable spark-history-server.service
sudo systemctl start spark-history-server.service || true
sudo systemctl enable spark-connect-server.service
sudo systemctl start spark-connect-server.service || true
sudo systemctl enable livy.service
sudo systemctl start livy.service || true

sudo -u ec2-user bash -c 'export HOME=/home/ec2-user && curl -s https://pyenv.run | bash'
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> /home/ec2-user/.bashrc
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> /home/ec2-user/.bashrc
echo 'eval "$(pyenv init -)"' >> /home/ec2-user/.bashrc
sudo -u ec2-user bash -c 'export HOME=/home/ec2-user PYENV_ROOT=/home/ec2-user/.pyenv PATH="/home/ec2-user/.pyenv/bin:$PATH" && eval "$(pyenv init -)" && pyenv install -s 3.11.9' 2>/dev/null || sudo -u ec2-user bash -c 'export HOME=/home/ec2-user PYENV_ROOT=/home/ec2-user/.pyenv PATH="/home/ec2-user/.pyenv/bin:$PATH" && eval "$(pyenv init -)" && pyenv install -s 3.11.6'
sudo -u ec2-user bash -c 'export HOME=/home/ec2-user PYENV_ROOT=/home/ec2-user/.pyenv PATH="/home/ec2-user/.pyenv/bin:$PATH" && eval "$(pyenv init -)" && pyenv global 3.11.9' 2>/dev/null || sudo -u ec2-user bash -c 'export HOME=/home/ec2-user PYENV_ROOT=/home/ec2-user/.pyenv PATH="/home/ec2-user/.pyenv/bin:$PATH" && eval "$(pyenv init -)" && pyenv global 3.11.6'
ln -sf /home/ec2-user/.pyenv/shims/python3 /usr/local/bin/python3-global
ln -sf /home/ec2-user/.pyenv/shims/pip3 /usr/local/bin/pip3-global
sudo -u ec2-user /home/ec2-user/.pyenv/shims/pip3 install --upgrade pip
sudo -u ec2-user /home/ec2-user/.pyenv/shims/pip3 install pyspark flask requests PyYAML cassandra-driver boto3 scylla-cqlsh scylla-driver

CASSANDRA_STRESS_VER=3.17.0
wget -q "https://github.com/scylladb/cassandra-stress/releases/download/v${CASSANDRA_STRESS_VER}/cassandra-stress-${CASSANDRA_STRESS_VER}-bin.tar.gz" -O /tmp/cassandra-stress.tar.gz
tar -xzf /tmp/cassandra-stress.tar.gz -C /opt
ln -sf /opt/cassandra-stress-${CASSANDRA_STRESS_VER}/bin/cassandra-stress /usr/local/bin/cassandra-stress 2>/dev/null || true
rm -f /tmp/cassandra-stress.tar.gz

SCYLLA_BENCH_VER=1.0.0
wget -q "https://github.com/scylladb/scylla-bench/releases/download/v${SCYLLA_BENCH_VER}/scylla-bench_${SCYLLA_BENCH_VER}_linux_amd64.tar.gz" -O /tmp/scylla-bench.tar.gz
tar -xzf /tmp/scylla-bench.tar.gz -C /opt
ln -sf /opt/scylla-bench /usr/local/bin/scylla-bench 2>/dev/null || ln -sf /opt/scylla-bench_${SCYLLA_BENCH_VER}_linux_amd64/scylla-bench /usr/local/bin/scylla-bench 2>/dev/null || true
rm -f /tmp/scylla-bench.tar.gz

mkdir -p "$(dirname "$DEPLOY_DIR")"
if [ -n "$REPO_URL" ] && [ "$REPO_URL" != "none" ]; then
  [ ! -d "$DEPLOY_DIR/.git" ] && git clone --depth 1 "$REPO_URL" "$DEPLOY_DIR" || true
fi
chown -R ec2-user:ec2-user "$DEPLOY_DIR" 2>/dev/null || true

cd "$DEPLOY_DIR" 2>/dev/null || { echo "Deploy dir not found"; exit 1; }
[ ! -f config.yaml ] && cp config.yaml.minimal config.yaml 2>/dev/null || touch config.yaml

JARS_DIR="${DEPLOY_DIR}/migrator/target/scala-2.13"
mkdir -p "$JARS_DIR"

if [ -n "$PREBUILT_BUCKET" ] && [ -n "$PREBUILT_KEY" ]; then
  aws s3 cp "s3://${PREBUILT_BUCKET}/${PREBUILT_KEY}" "$JARS_DIR/" 2>/dev/null || true
fi

if [ -z "$(ls -A $JARS_DIR/*assembly*.jar 2>/dev/null)" ]; then
  curl -sL "https://github.com/coursier/launchers/raw/master/cs-x86_64-pc-linux.gz" | gzip -d > /usr/local/bin/cs
  chmod +x /usr/local/bin/cs
  /usr/local/bin/cs install sbt 2>/dev/null || true
  export PATH="/root/.local/share/coursier/bin:/usr/local/bin:$PATH"
  sbt -batch migrator/assembly 2>&1 | tail -30
  [ -z "$(ls -A $JARS_DIR/*assembly*.jar 2>/dev/null)" ] && { echo "sbt build failed"; exit 1; }
fi
chown -R ec2-user:ec2-user "$DEPLOY_DIR" 2>/dev/null || true

ln -sf /home/ec2-user/spark /spark 2>/dev/null || true
ln -sf "$DEPLOY_DIR" /app 2>/dev/null || true
ln -sf "$JARS_DIR" /jars 2>/dev/null || true

cat > /etc/systemd/system/scylla-migrator-web.service << 'SVCEOF'
[Unit]
Description=Scylla Migrator Web App
After=network.target spark-master.service

[Service]
Type=simple
User=ec2-user
Group=ec2-user
WorkingDirectory=/home/ec2-user/scylla-migrator/web-app
EnvironmentFile=-/etc/scylla-migrator.env
Environment="SPARK_MASTER_HOST=localhost"
Environment="SPARK_HOME=/home/ec2-user/spark"
Environment="SPARK_EVENTS=file:/home/ec2-user/spark-events"
Environment="MIGRATOR_CONFIG_PATH=/home/ec2-user/scylla-migrator/config.yaml"
Environment="LIVY_URL=http://127.0.0.1:8998"
Environment="FLASK_APP=app.py"
Environment="PATH=/home/ec2-user/spark/bin:/home/ec2-user/spark/sbin:/usr/local/bin:/home/ec2-user/.pyenv/shims:/usr/bin"
ExecStart=/home/ec2-user/.pyenv/shims/python -m flask run --host=0.0.0.0 --port=5000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF
sed -i "/EnvironmentFile=-\\/etc\\/scylla-migrator.env/a Environment=EXTERNAL_HOST=$EXTERNAL_HOST" /etc/systemd/system/scylla-migrator-web.service
sudo systemctl daemon-reload
if [ -d "$DEPLOY_DIR/web-app" ]; then
  sudo systemctl enable scylla-migrator-web
  sudo systemctl start scylla-migrator-web
else
  echo "WARNING: web-app not found in $DEPLOY_DIR. Use RepoUrl parameter to point to a fork that includes web-app (e.g. your fork with web-app). Skipping web service."
fi

echo 'export PATH=/home/ec2-user/spark/bin:/home/ec2-user/spark/sbin:$PATH' >> /home/ec2-user/.bashrc
echo 'export SPARK_HOME=/home/ec2-user/spark' >> /home/ec2-user/.bashrc
echo 'export PATH=/home/ec2-user/spark/bin:/home/ec2-user/spark/sbin:$PATH' | tee -a /etc/profile.d/spark.sh
echo 'export SPARK_HOME=/home/ec2-user/spark' | tee -a /etc/profile.d/spark.sh

echo "=== Bootstrap complete ==="
echo "Web app: http://${EXTERNAL_HOST}:5000"
echo "Spark Master: http://${EXTERNAL_HOST}:8080"
echo "Spark History: http://${EXTERNAL_HOST}:18080"
echo "Spark Worker: http://${EXTERNAL_HOST}:8081"
echo "Spark Connect: sc://${EXTERNAL_HOST}:15002"
echo "Livy: http://${EXTERNAL_HOST}:8998"

nohup bash -c 'sleep 120 && for _ in 1 2 3; do TOKEN=$(curl -sf -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" -m 5 2>/dev/null) || true; if [ -n "$TOKEN" ]; then INST_ID=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/instance-id" -m 5 2>/dev/null) || true; REG=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/placement/region" -m 5 2>/dev/null) || true; fi; [ -n "$INST_ID" ] && [ -n "$REG" ] && break; sleep 10; done && [ -n "$INST_ID" ] && [ -n "$REG" ] && (EXTERNAL_HOST_NEW=$(aws ec2 describe-instances --instance-ids $INST_ID --query "Reservations[0].Instances[0].NetworkInterfaces[0].Association.PublicDnsName" --output text --region $REG 2>/dev/null); [ -z "$EXTERNAL_HOST_NEW" ] || [ "$EXTERNAL_HOST_NEW" = "None" ] && EXTERNAL_HOST_NEW=$(aws ec2 describe-instances --instance-ids $INST_ID --query "Reservations[0].Instances[0].PublicDnsName" --output text --region $REG 2>/dev/null); [ -z "$EXTERNAL_HOST_NEW" ] || [ "$EXTERNAL_HOST_NEW" = "None" ] && EXTERNAL_HOST_NEW=$(aws ec2 describe-instances --instance-ids $INST_ID --query "Reservations[0].Instances[0].PublicIpAddress" --output text --region $REG 2>/dev/null); [ -z "$EXTERNAL_HOST_NEW" ] || [ "$EXTERNAL_HOST_NEW" = "None" ] && EXTERNAL_HOST_NEW=$(aws ec2 describe-instances --instance-ids $INST_ID --query "Reservations[0].Instances[0].PrivateIpAddress" --output text --region $REG 2>/dev/null); [ -n "$EXTERNAL_HOST_NEW" ] && (echo "EXTERNAL_HOST=$EXTERNAL_HOST_NEW" | sudo tee /etc/scylla-migrator.env && { echo "SPARK_PUBLIC_DNS=$EXTERNAL_HOST_NEW"; echo "SPARK_MASTER_OPTS=-Dspark.ui.reverseProxy=true -Dspark.master.rest.host=$EXTERNAL_HOST_NEW"; echo "SPARK_WORKER_OPTS=-Dspark.ui.reverseProxy=true"; echo "SPARK_HISTORY_OPTS=-Dspark.history.ui.bindAddress=0.0.0.0 -Dspark.history.fs.logDirectory=file:/home/ec2-user/spark-events -Dspark.ui.reverseProxy=true -Dspark.history.ui.reverseProxyUrl=http://$EXTERNAL_HOST_NEW:18080"; } | sudo tee /etc/scylla-migrator-spark.env && sudo sed -i "s@Environment=EXTERNAL_HOST=.*@Environment=EXTERNAL_HOST=$EXTERNAL_HOST_NEW@" /etc/systemd/system/scylla-migrator-web.service 2>/dev/null && sudo systemctl daemon-reload && sudo systemctl restart scylla-migrator-web && sudo systemctl restart spark-master spark-worker spark-history-server spark-connect-server livy && echo "EXTERNAL_HOST and Spark config updated; web app and Spark daemons restarted"))' >> /var/log/external-host-update.log 2>&1 &
