import boto3


def upload_report(bucket, key, data):
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=data)
