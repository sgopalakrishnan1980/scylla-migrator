# CloudFormation Deployment

Deploy Scylla Migrator infrastructure (Spark + web app) into an **existing VPC** with CloudFormation. The infra focuses on configuration, Spark setup, and the web app — no Scylla/Alternator. Connect to your own target cluster. The template lets you select a VPC and subnet from dropdowns and adds a security group rule allowing **all inbound traffic from the VPC** to the deployed host.

## Files

- `scylla-migrator.yaml` — Main CloudFormation template
- `parameters.example.json` — Example parameters file

## Parameters

| Parameter | Description |
|-----------|-------------|
| VpcId | Select your VPC (dropdown in Console) |
| SubnetId | Select a subnet **in the chosen VPC** |
| VpcCidrBlock | CIDR of the selected VPC (e.g. `10.0.0.0/16`). Used for the inbound rule allowing all traffic from the VPC. |
| KeyName | SSH key pair |
| InstanceType | m6i.6xlarge (24 vCPUs) recommended |
| SshAllowedCidr | CIDR for SSH and web access |
| IamInstanceProfile | Optional — for S3/DynamoDB. Leave empty to use default (includes SSM for easy access) |

## Security Group

- **All traffic from VPC**: Inbound rule with source = `VpcCidrBlock` (IpProtocol: -1) — allows any resource in the VPC to reach the migrator instance
- SSH, Web app, Spark ports from `SshAllowedCidr`

## Quick Deploy

```bash
aws cloudformation create-stack \
  --stack-name scylla-migrator \
  --template-body file://scylla-migrator.yaml \
  --parameters file://parameters.example.json
```

See [docs/EC2-DEPLOYMENT.md](../docs/EC2-DEPLOYMENT.md) for full instructions.
