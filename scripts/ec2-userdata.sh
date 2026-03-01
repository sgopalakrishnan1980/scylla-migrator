#!/bin/bash
# EC2 user data script - installs Docker, clones scylla-migrator, and starts the stack
# Use with EC2 Launch Template (Amazon Linux 2023 or Ubuntu 22.04)
# Variables REPO_URL, DEPLOY_DIR can be set via Terraform templatefile or environment

set -e
exec > >(tee /var/log/user-data.log) 2>&1

REPO_URL="${REPO_URL:-https://github.com/scylladb/scylla-migrator.git}"
DEPLOY_DIR="${DEPLOY_DIR:-/home/ec2-user/scylla-migrator}"

echo "=== Scylla Migrator EC2 Bootstrap ==="

# Detect OS
if [ -f /etc/os-release ]; then
  . /etc/os-release
  OS=$ID
else
  OS=unknown
fi

# Install Docker and Docker Compose
install_docker() {
  if command -v docker &>/dev/null; then
    echo "Docker already installed"
    return
  fi

  if [ "$OS" = "amzn" ] || [ "$OS" = "rhel" ]; then
    yum update -y
    yum install -y docker
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ec2-user
  elif [ "$OS" = "ubuntu" ]; then
    apt-get update
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ubuntu
  else
    echo "Unsupported OS: $OS"
    exit 1
  fi

  # Install Docker Compose v2 (plugin)
  if ! docker compose version &>/dev/null; then
    if [ "$OS" = "amzn" ]; then
      curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
      chmod +x /usr/local/bin/docker-compose
      ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose
    fi
  fi
}

install_docker

# Wait for docker
for i in $(seq 1 30); do
  if docker info &>/dev/null; then break; fi
  sleep 2
done

# Clone or copy scylla-migrator
if [ "$OS" = "ubuntu" ]; then
  DEPLOY_DIR="${DEPLOY_DIR:-/home/ubuntu/scylla-migrator}"
fi

mkdir -p "$(dirname "$DEPLOY_DIR")"
if [ -n "$REPO_URL" ] && [ "$REPO_URL" != "none" ]; then
  if [ ! -d "$DEPLOY_DIR/.git" ]; then
    git clone --depth 1 "$REPO_URL" "$DEPLOY_DIR" || true
  fi
fi

# If S3 bucket provided, sync from there instead
if [ -n "$S3_BUCKET" ] && [ -n "$S3_PREFIX" ]; then
  aws s3 sync "s3://${S3_BUCKET}/${S3_PREFIX}" "$DEPLOY_DIR" --delete 2>/dev/null || true
fi

cd "$DEPLOY_DIR" 2>/dev/null || { echo "Deploy dir not found: $DEPLOY_DIR"; exit 1; }

# Build migrator JAR if sbt available
if command -v sbt &>/dev/null; then
  sbt migrator/assembly 2>/dev/null || true
fi

# Create data dirs
mkdir -p data/spark-master data/spark-worker data/spark-events

# Use public IP for Spark UI links (browser-facing URLs)
EXTERNAL_HOST=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)
export EXTERNAL_HOST

# Start services (Spark + web app only — no Scylla/Alternator)
echo "Starting Docker Compose (Spark + web app)..."
docker compose -f docker-compose.ec2.yml up -d

echo "Waiting 2 minutes for services to stabilize..."
sleep 120

if [ -f "$DEPLOY_DIR/scripts/post-deploy-wait.sh" ]; then
  bash "$DEPLOY_DIR/scripts/post-deploy-wait.sh" || true
fi

echo "=== Bootstrap complete ==="
echo "Web app: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo localhost):5000"
echo "Spark Master: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo localhost):8080"
echo "Spark History: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo localhost):18080"
