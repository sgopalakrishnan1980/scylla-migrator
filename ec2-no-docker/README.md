# Scylla Migrator - EC2 without Docker

Deploys a single Amazon Linux EC2 instance with **SSM** (Session Manager), **Apache Spark 3.5.8** (master + worker), and the **Python Flask web app**. No Docker required—everything runs natively on the host.

## What gets installed

| Component       | Version / details                                      |
|----------------|---------------------------------------------------------|
| Amazon Linux   | AL2023 (latest AMI)                                    |
| Spark          | 3.5.8 (bin-hadoop3-scala2.13)                          |
| Java           | Amazon Corretto 11                                      |
| Flask web app  | scylla-migrator web-app from repo                       |
| Migrator JAR   | Built with sbt, or provided via S3 (see parameters)     |

## Prerequisites

- AWS CLI configured
- VPC and subnet with internet access
- SSH key pair in the target region
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
| RepoUrl            | github.com/scylladb/scylla-migrator    | Git repo URL                                     |
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

### URLs (replace `<public-ip>` with the instance public IP)

| Service        | URL                        |
|----------------|----------------------------|
| Web app        | http://\<public-ip\>:5000  |
| Spark Master   | http://\<public-ip\>:8080  |
| Spark History  | http://\<public-ip\>:18080 |
| Spark Worker   | http://\<public-ip\>:8081  |

### Connect via SSM (no SSH key needed)

```bash
aws ssm start-session --target <instance-id>
```

### Config

Edit `/home/ec2-user/scylla-migrator/config.yaml` with your source and target settings.
