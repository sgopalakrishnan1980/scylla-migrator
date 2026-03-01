# Scylla Migrator EC2 Launch Template - Terraform
# Deploys a single EC2 instance with Docker running Spark + web app (config, Spark setup, web UI — no Alternator)

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "aws_region" {
  default     = "us-east-1"
  description = "AWS region"
}

variable "instance_type" {
  default     = "m6i.6xlarge"
  description = "EC2 instance type (24 vCPUs recommended)"
}

variable "key_name" {
  type        = string
  description = "SSH key pair name for EC2 access"
}

variable "repo_url" {
  default     = "https://github.com/scylladb/scylla-migrator.git"
  description = "Git repo URL for scylla-migrator (or 'none' to skip clone)"
}

variable "allowed_cidr" {
  default     = "0.0.0.0/0"
  description = "CIDR allowed for SSH and web access (restrict in production)"
}

provider "aws" {
  region = var.aws_region
}

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

data "local_file" "userdata" {
  filename = "${path.module}/../scripts/ec2-userdata.sh"
}

# IAM role for SSM Agent (Session Manager) — easy SSH-free access
resource "aws_iam_role" "migrator_ssm" {
  name = "scylla-migrator-ssm"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.migrator_ssm.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "migrator" {
  name = "scylla-migrator-ssm"
  role = aws_iam_role.migrator_ssm.name
}

resource "aws_security_group" "migrator" {
  name        = "scylla-migrator-sg"
  description = "Scylla Migrator - Spark, Web App"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
    description = "SSH"
  }

  ingress {
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
    description = "Web App"
  }

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
    description = "Spark Master UI"
  }

  ingress {
    from_port   = 18080
    to_port     = 18080
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
    description = "Spark History Server"
  }

  ingress {
    from_port   = 8081
    to_port     = 8081
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
    description = "Spark Worker UI"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "migrator" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  iam_instance_profile   = aws_iam_instance_profile.migrator.name
  vpc_security_group_ids = [aws_security_group.migrator.id]

  user_data = templatefile("${path.module}/../scripts/ec2-userdata.sh", {
    REPO_URL   = var.repo_url
    DEPLOY_DIR = "/home/ec2-user/scylla-migrator"
  })

  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  tags = {
    Name = "scylla-migrator"
  }
}

output "public_ip" {
  value       = aws_instance.migrator.public_ip
  description = "Public IP of the migrator instance"
}

output "web_app_url" {
  value       = "http://${aws_instance.migrator.public_ip}:5000"
  description = "Web app URL"
}

output "spark_master_url" {
  value       = "http://${aws_instance.migrator.public_ip}:8080"
  description = "Spark Master UI URL"
}

output "ssh_command" {
  value       = "ssh -i <your-key.pem> ec2-user@${aws_instance.migrator.public_ip}"
  description = "SSH command to connect (key-based)"
}

output "ssm_connect_command" {
  value       = "aws ssm start-session --target ${aws_instance.migrator.id}"
  description = "Connect via SSM (no SSH key, no port 22 required)"
}
