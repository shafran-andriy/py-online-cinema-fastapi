class S3StorageInterface:
    def upload_file(self, file_path: str, key: str) -> str:
        """Upload a file to S3-compatible storage and return the stored key or URL."""
        raise NotImplementedError


class S3StorageClient(S3StorageInterface):
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket_name: str):
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name

    def upload_file(self, file_path: str, key: str) -> str:
        # Placeholder implementation for tests
        return f"{self.endpoint_url}/{self.bucket_name}/{key}"
