# Scylla Migrator EC2 Launch Template - Terraform
# Deploys a single EC2 instance with Docker running the full migrator stack

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

resource "aws_security_group" "migrator" {
  name        = "scylla-migrator-sg"
  description = "Scylla Migrator - Spark, Alternator, Web App"

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

  ingress {
    from_port   = 9042
    to_port     = 9042
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
    description = "Scylla CQL"
  }

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
    description = "Scylla Alternator"
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
  description = "SSH command to connect"
}
