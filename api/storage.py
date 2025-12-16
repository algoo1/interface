import os
import boto3
from botocore.config import Config

class StorageManager:
    def __init__(self):
        self.endpoint_url = os.getenv("R2_ENDPOINT_URL")
        self.access_key_id = os.getenv("R2_ACCESS_KEY_ID")
        self.secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = os.getenv("R2_BUCKET_NAME")
        
        if not all([self.endpoint_url, self.access_key_id, self.secret_access_key, self.bucket_name]):
            print("Warning: Cloudflare R2 credentials missing. Storage features will not work.")
            self.s3_client = None
        else:
            self.s3_client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=Config(signature_version='s3v4'),
                region_name='auto' # Cloudflare R2 uses 'auto'
            )

    def generate_presigned_upload_url(self, object_name, expiration=3600):
        if not self.s3_client:
            return None
        try:
            response = self.s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': object_name,
                    # 'ContentType': 'video/mp4' # Optional, enforces content type
                },
                ExpiresIn=expiration
            )
            return response
        except Exception as e:
            print(f"Error generating upload URL: {e}")
            return None

    def generate_presigned_download_url(self, object_name, expiration=3600):
        if not self.s3_client:
            return None
        try:
            response = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': object_name
                },
                ExpiresIn=expiration
            )
            return response
        except Exception as e:
            print(f"Error generating download URL: {e}")
            return None
