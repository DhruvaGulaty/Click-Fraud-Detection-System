"""
clickfraud_aws_check.py

Run this to verify your AWS credentials and the AWS services used in the Click-Fraud Detector (Data Orch) project.
Services checked:
 - STS (credentials)
 - S3 (bucket)
 - SageMaker (endpoint)
 - CloudWatch Logs (log group)
 - CloudFront (distribution)
 - AWS Glue (database + table existence)

Usage:
  - Create a .env with the variables listed below (example provided after the script).
  - python clickfraud_aws_check.py
"""
import os
import sys
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

load_dotenv()

# AWS config from .env
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

# Project-specific resources (set these in .env)
S3_BUCKET = os.getenv("S3_BUCKET")                          # Bucket for data / feature store
SAGEMAKER_ENDPOINT = os.getenv("SAGEMAKER_ENDPOINT")        # e.g. click-fraud-detector-1
CLOUDWATCH_LOG_GROUP_PREFIX = os.getenv("CLOUDWATCH_LOG_GROUP_PREFIX", "clickfraud-logs")

# CloudFront distribution id to check (previously requested)
CLOUDFRONT_DISTRIBUTION_ID = os.getenv("CLOUDFRONT_DISTRIBUTION_ID", "ELF58EFRI9CJG")

# Glue database and table to check (new)
GLUE_DATABASE = os.getenv("GLUE_DATABASE")  # e.g. 'clickfraud_db'
GLUE_TABLE = os.getenv("GLUE_TABLE")        # e.g. 'sessions_features'

def print_config():
    print("\n" + "="*72)
    print("CLICK-FRAUD DETECTOR - AWS CONFIGURATION CHECK")
    print("="*72)
    print(f"AWS Access Key ID: {'[OK]' if AWS_ACCESS_KEY_ID else '[MISSING]'}")
    print(f"AWS Secret Access Key: {'[OK]' if AWS_SECRET_ACCESS_KEY else '[MISSING]'}")
    print(f"AWS Region: {AWS_REGION}")
    print(f"S3 Bucket: {S3_BUCKET or '[MISSING]'}")
    print(f"SageMaker Endpoint: {SAGEMAKER_ENDPOINT or '[MISSING]'}")
    print(f"CloudWatch Log Group Prefix: {CLOUDWATCH_LOG_GROUP_PREFIX}")
    print(f"CloudFront Distribution ID (checked): {CLOUDFRONT_DISTRIBUTION_ID}")
    print(f"Glue Database: {GLUE_DATABASE or '[MISSING]'}")
    print(f"Glue Table: {GLUE_TABLE or '[MISSING]'}")
    print("="*72 + "\n")

def client(service):
    """Helper to create boto3 client with explicit creds (so .env is respected)."""
    # CloudFront is a global service; region arg is ignored but harmless if provided
    return boto3.client(
        service,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )

def test_credentials():
    print("-> Testing AWS credentials (STS)...")
    try:
        sts = client('sts')
        identity = sts.get_caller_identity()
        print("  [OK] Credentials valid")
        print(f"    Account: {identity.get('Account')}")
        print(f"    ARN: {identity.get('Arn')}")
        return True
    except NoCredentialsError:
        print("  [MISSING] No credentials found.")
        return False
    except ClientError as e:
        print(f"  [ERROR] STS ClientError: {e.response['Error'].get('Message')}")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def test_s3():
    print("\n-> Testing S3 bucket access...")
    if not S3_BUCKET:
        print("  [MISSING] S3_BUCKET not configured")
        return False
    try:
        s3 = client('s3')
        s3.head_bucket(Bucket=S3_BUCKET)
        print(f"  [OK] S3 Bucket accessible: {S3_BUCKET}")
        return True
    except ClientError as e:
        code = e.response['Error'].get('Code', '')
        if code in ("404", "NoSuchBucket"):
            print(f"  [ERROR] S3 Bucket not found: {S3_BUCKET}")
        else:
            print(f"  [ERROR] S3 Error: {e.response['Error'].get('Message')}")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def test_sagemaker():
    print("\n-> Testing SageMaker endpoint (inference)...")
    if not SAGEMAKER_ENDPOINT:
        print("  [MISSING] SAGEMAKER_ENDPOINT not configured")
        return False
    try:
        sm = client('sagemaker')
        resp = sm.describe_endpoint(EndpointName=SAGEMAKER_ENDPOINT)
        status = resp.get('EndpointStatus')
        print(f"  [OK] Endpoint found: {SAGEMAKER_ENDPOINT}")
        print(f"    Status: {status}")
        if status not in ('InService',):
            print("    [WARN] Endpoint not InService (cannot call).")
        return True
    except ClientError as e:
        code = e.response['Error'].get('Code', '')
        if code == 'ValidationException' or 'Could not find' in str(e):
            print(f"  [ERROR] SageMaker endpoint not found: {SAGEMAKER_ENDPOINT}")
        else:
            print(f"  [ERROR] SageMaker Error: {e.response['Error'].get('Message')}")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def test_cloudwatch_logs():
    print("\n-> Testing CloudWatch Logs (log group prefix)...")
    try:
        logs = client('logs')
        resp = logs.describe_log_groups(logGroupNamePrefix=CLOUDWATCH_LOG_GROUP_PREFIX, limit=5)
        groups = resp.get('logGroups', [])
        if groups:
            print(f"  [OK] Found CloudWatch Log Group(s) with prefix '{CLOUDWATCH_LOG_GROUP_PREFIX}':")
            for g in groups[:5]:
                print(f"    - {g.get('logGroupName')}")
            return True
        else:
            print(f"  [WARN] No log groups with prefix '{CLOUDWATCH_LOG_GROUP_PREFIX}' found.")
            print("    They will be created automatically once your app logs something.")
            return True
    except ClientError as e:
        print(f"  [ERROR] CloudWatch Logs Error: {e.response['Error'].get('Message')}")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def test_cloudfront(distribution_id=CLOUDFRONT_DISTRIBUTION_ID):
    """
    Check CloudFront distribution presence and basic status.
    Note: CloudFront is a global service; describe/get calls do not require region.
    """
    print("\n-> Testing CloudFront distribution...")
    if not distribution_id:
        print("  [MISSING] CloudFront distribution ID not configured")
        return False
    try:
        cf = client('cloudfront')
        resp = cf.get_distribution(Id=distribution_id)
        dist = resp.get('Distribution', {})
        status = dist.get('Status', 'Unknown')
        domain = dist.get('DomainName', 'Unknown')
        enabled = dist.get('DistributionConfig', {}).get('Enabled', None)
        print(f"  [OK] CloudFront distribution found: {distribution_id}")
        print(f"    Status: {status}")
        print(f"    DomainName: {domain}")
        if enabled is not None:
            print(f"    Enabled: {enabled}")
        return True
    except ClientError as e:
        code = e.response['Error'].get('Code', '')
        # CloudFront returns NoSuchDistribution for missing distributions
        if code == 'NoSuchDistribution' or 'NoSuchDistribution' in str(e):
            print(f"  [ERROR] CloudFront distribution not found: {distribution_id}")
        else:
            print(f"  [ERROR] CloudFront Error: {e.response['Error'].get('Message')}")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def test_glue_table(database=GLUE_DATABASE, table_name=GLUE_TABLE):
    """
    Check whether a Glue table exists in the given Glue database.
    Uses get_table(database, tableName).
    """
    print("\n-> Testing AWS Glue table existence...")
    if not database:
        print("  [MISSING] GLUE_DATABASE not configured")
        return False
    if not table_name:
        print("  [MISSING] GLUE_TABLE not configured")
        return False
    try:
        glue = client('glue')
        resp = glue.get_table(DatabaseName=database, Name=table_name)
        table = resp.get('Table', {})
        create_time = table.get('CreateTime')
        last_access = table.get('LastAccessTime', 'N/A')
        print(f"  [OK] Glue table found: {database}.{table_name}")
        print(f"    CreateTime: {create_time}")
        print(f"    LastAccessTime: {last_access}")
        return True
    except ClientError as e:
        code = e.response['Error'].get('Code', '')
        # Glue returns EntityNotFoundException for missing DB or table
        if code == 'EntityNotFoundException' or 'EntityNotFoundException' in str(e):
            # Distinguish whether DB exists or table missing by listing databases/tables
            try:
                glue = client('glue')
                # check database exists
                dblist = glue.get_databases(MaxResults=100)
                db_names = [d['Name'] for d in dblist.get('DatabaseList', [])]
                if database not in db_names:
                    print(f"  [ERROR] Glue database not found: {database}")
                else:
                    print(f"  [ERROR] Glue table not found in database '{database}': {table_name}")
            except Exception:
                print(f"  [ERROR] Glue Entity not found (db or table): {e.response['Error'].get('Message')}")
            return False
        else:
            print(f"  [ERROR] Glue Error: {e.response['Error'].get('Message')}")
            return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def main():
    print_config()
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        print("ERROR: AWS credentials not found in environment (.env).")
        print("Please populate AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and try again.")
        sys.exit(1)

    results = {
        "Credentials": test_credentials(),
        "S3": test_s3(),
        "SageMaker": test_sagemaker(),
        "CloudWatchLogs": test_cloudwatch_logs(),
        "CloudFront": test_cloudfront(),
        "GlueTable": test_glue_table()
    }

    print("\n" + "="*72)
    print("TEST SUMMARY")
    print("="*72)
    for k, v in results.items():
        status = "PASS" if v else "FAIL"
        marker = "[OK]" if v else "[FAIL]"
        print(f"{marker} {k}: {status}")
    print("="*72)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    if passed == total:
        print("\n[OK] All checks passed.")
    else:
        print("\n[WARN] Some services need attention. Check logs above and the AWS console.")
    print("\n")

if __name__ == "__main__":
    main()
