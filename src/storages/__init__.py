import asyncio
import io


class S3StorageInterface:
    def upload_file(self, file_path: str, key: str) -> str:
        """Upload a file by path to S3-compatible storage and return the stored key or URL."""
        raise NotImplementedError

    async def upload_fileobj(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        """Upload raw bytes to S3-compatible storage and return the public URL."""
        raise NotImplementedError


class S3StorageClient(S3StorageInterface):
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket_name: str):
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name

    def upload_file(self, file_path: str, key: str) -> str:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )
        s3.upload_file(file_path, self.bucket_name, key)
        return f"{self.endpoint_url}/{self.bucket_name}/{key}"

    async def upload_fileobj(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        def _do_upload():
            import boto3
            s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
            )
            s3.upload_fileobj(
                io.BytesIO(data),
                self.bucket_name,
                key,
                ExtraArgs={"ContentType": content_type},
            )
            return f"{self.endpoint_url}/{self.bucket_name}/{key}"

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_upload)
