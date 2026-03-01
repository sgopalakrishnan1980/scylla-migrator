# EC2 Deployment Guide

Deploy the Scylla Migrator infrastructure (Spark master + worker + web app) on a single EC2 instance. Focused on **configuration**, **Spark setup**, and the **web app** for easy use. No Scylla/Alternator — connect to your own target cluster.

## Prerequisites

- AWS CLI configured
- SSH key pair in EC2
- Terraform or AWS CloudFormation (optional, for IaC)

---

## Option 1: CloudFormation (Recommended for Existing VPCs)

Deploy into an **existing VPC** with a dropdown to select VPC and subnet. The security group includes an inbound rule allowing **all traffic from the VPC** to the deployed host.

### Via AWS Console

1. Open **CloudFormation** → **Create stack** → **With new resources**
2. Upload `cloudformation/scylla-migrator.yaml` or specify the S3 URL
3. Fill in parameters:
   - **VpcId**: Select your VPC from the dropdown
   - **SubnetId**: Select a subnet in that VPC (must be in the chosen VPC)
   - **VpcCidrBlock**: CIDR of the selected VPC (e.g. `10.0.0.0/16`) — used for the inbound rule allowing all traffic from the VPC
   - **KeyName**: Your SSH key pair
   - **InstanceType**: m6i.6xlarge (default, 24 vCPUs)
   - **SshAllowedCidr**: CIDR for SSH and web access (default `0.0.0.0/0`; restrict in production)
   - **IamInstanceProfile**: Optional IAM instance profile for S3/DynamoDB access
4. Create the stack. Wait 5–10 minutes for bootstrap.
5. Use **Outputs** for Web app URL, Spark Master URL, SSH command, and **SSM connect** command.

**SSM access (recommended):** Leave `IamInstanceProfile` empty to use the default role with SSM. Then connect without SSH keys or port 22:

```bash
aws ssm start-session --target <instance-id>
```

See [SSM / SSH-over-SSM](#ssm--ssh-over-ssm) below.

### Via AWS CLI

```bash
# List VPCs and subnets to get IDs
aws ec2 describe-vpcs --query 'Vpcs[*].[VpcId,CidrBlock]' --output table
aws ec2 describe-subnets --filters "Name=vpc-id,Values=YOUR_VPC_ID" --query 'Subnets[*].[SubnetId,AvailabilityZone,CidrBlock]' --output table

# Create stack
aws cloudformation create-stack \
  --stack-name scylla-migrator \
  --template-body file://cloudformation/scylla-migrator.yaml \
  --parameters \
    ParameterKey=VpcId,ParameterValue=vpc-xxxxxxxxx \
    ParameterKey=SubnetId,ParameterValue=subnet-xxxxxxxxx \
    ParameterKey=VpcCidrBlock,ParameterValue=10.0.0.0/16 \
    ParameterKey=KeyName,ParameterValue=your-key-pair-name

# Check status
aws cloudformation describe-stacks --stack-name scylla-migrator --query 'Stacks[0].Outputs'
```

### Security Group Rules (CloudFormation)

- **SSH (22)**: From `SshAllowedCidr`
- **All traffic from VPC**: Inbound from `VpcCidrBlock` (allows any resource in the VPC to reach the deployed host)
- **Web app (5000), Spark (8080, 18080, 8081)**: From `SshAllowedCidr`

---

## Option 2: Terraform

```bash
cd terraform
terraform init
terraform plan -var="key_name=YOUR_KEY_NAME"
terraform apply -var="key_name=YOUR_KEY_NAME"
```

Outputs will show the public IP and URLs. Terraform creates a new VPC and security group by default.

---

## Option 3: Manual Launch

1. **Create security group** with inbound rules:
   - 22 (SSH)
   - 5000 (Web app)
   - 8080 (Spark Master)
   - 18080 (Spark History)
   - 8081 (Spark Worker)

2. **Launch instance** (m6i.6xlarge recommended for 24 vCPUs):
   - AMI: Amazon Linux 2023
   - Instance type: m6i.6xlarge or c6i.6xlarge
   - User data: contents of `scripts/ec2-userdata.sh` (uses `docker-compose.ec2.yml` — Spark + web app only)

3. **Post-launch**: Wait 5-10 minutes, then access:
   - Web app: http://<public-ip>:5000
   - Spark Master: http://<public-ip>:8080
   - Spark History: http://<public-ip>:18080
   - Spark Worker UI: http://<public-ip>:8081

   The web app's Spark UI buttons use the instance public IP (via `EXTERNAL_HOST`) so links work from your browser.

---

## SSM / SSH-over-SSM

AWS Systems Manager Session Manager lets you connect to the instance without SSH keys or opening port 22. The CloudFormation template (with default `IamInstanceProfile`) and Terraform both attach an IAM role with `AmazonSSMManagedInstanceCore`. The SSM agent is pre-installed on Amazon Linux 2023.

### Connect via SSM (shell)

```bash
aws ssm start-session --target <instance-id>
```

Get the instance ID from CloudFormation **Outputs** → `InstanceId`, or Terraform `terraform output` (use the instance ID, not the IP).

### SSH over SSM (scp, rsync, SSH tools)

Add to `~/.ssh/config`:

```
Host i-* mi-*
  ProxyCommand sh -c "aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'"
```

Then connect using the instance ID as the hostname:

```bash
ssh ec2-user@i-0123456789abcdef0
```

### Prerequisites

- **AWS CLI** with Session Manager plugin: `session-manager-plugin` (install via `aws cli` or [AWS docs](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html))
- **IAM permissions** to call `ssm:StartSession` (or use an IAM user/role with `AmazonSSMManagedInstanceCore` or `SSMFullAccess`)
- Instance must reach SSM endpoints (internet or VPC endpoints for `ssmmessages`, `ssm`, `ec2messages`)

If using a **custom IamInstanceProfile**, add `AmazonSSMManagedInstanceCore` to that role for SSM access.

---

## Customization

- **Custom repo**: Set `REPO_URL` (CloudFormation/Terraform) or in user data
- **S3 artifact**: Set `S3_BUCKET` and `S3_PREFIX` in user data to sync from S3 instead of git
- **IAM**: Attach role with S3/DynamoDB permissions if migrating from AWS
