import boto3
from mypy_boto3_s3 import S3Client
from config import ConfigProvider
from logger_provider import LoggerProvider

log = LoggerProvider.get_logger()


class S3ClientProvider:
    cfg = ConfigProvider.get_config()
    client: S3Client | None = None

    @classmethod
    def get_s3_client(cls):
        if cls.client is None:
            cls.client = boto3.client(
                's3', endpoint_url=cls.cfg.S3_ENDPOINT_URL, aws_access_key_id=cls.cfg.S3_ACCESS_KEY,
                aws_secret_access_key=cls.cfg.S3_SECRET_KEY, region_name=cls.cfg.S3_REGION)
        return cls.client


class ObjectStorage:
    '''
    Implementation of the object storage using S3.
    '''

    def __init__(self) -> None:
        cfg = ConfigProvider.get_config()
        self.bucket_name = cfg.S3_BUCKET_NAME
        self.s3_client = S3ClientProvider.get_s3_client()
        self.ROOT = 'job-aggregator'

    def upload_coverletter(self, username: str, job_id: str, file_path: str) -> str:
        object_key = f'{self.ROOT}/{username}/cover_letters/{job_id}.pdf'
        upload_log = log.bind(username=username, job_id=job_id, object_key=object_key)
        upload_log.debug("Uploading cover letter PDF to S3")
        self.s3_client.upload_file(file_path, self.bucket_name, object_key)
        upload_log.info("Cover letter PDF uploaded")
        return object_key

    def upload_coverletter_json(self, username: str, job_id: str, file_path: str) -> str:
        object_key = f'{self.ROOT}/{username}/cover_letters/{job_id}.json'
        upload_log = log.bind(username=username, job_id=job_id, object_key=object_key)
        upload_log.debug("Uploading cover letter JSON to S3")
        self.s3_client.upload_file(file_path, self.bucket_name, object_key)
        upload_log.info("Cover letter JSON uploaded")
        return object_key

    def get_coverletter(self, username: str, job_id: str, file_path: str) -> str:
        object_key = f'{self.ROOT}/{username}/cover_letters/{job_id}.pdf'
        log.bind(username=username, job_id=job_id, object_key=object_key).debug("Downloading cover letter from S3")
        self.s3_client.download_file(self.bucket_name, object_key, file_path)
        return file_path

    def get_coverletter_md(self, username: str, job_id: str, file_path: str) -> str:
        object_key = f'{self.ROOT}/{username}/cover_letters/{job_id}.md'
        log.bind(username=username, job_id=job_id, object_key=object_key).debug("Downloading cover letter from S3")
        self.s3_client.download_file(self.bucket_name, object_key, file_path)
        return file_path

    def get_coverletter_json(self, username: str, job_id: str, file_path: str) -> str:
        object_key = f'{self.ROOT}/{username}/cover_letters/{job_id}.json'
        log.bind(username=username, job_id=job_id, object_key=object_key).debug("Downloading cover letter JSON from S3")
        self.s3_client.download_file(self.bucket_name, object_key, file_path)
        return file_path

    def get_object_bytes(self, object_key: str) -> bytes:
        """Fetch object content from S3 by key. Returns raw bytes."""
        log.bind(object_key=object_key).debug("Fetching object bytes from S3")
        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=object_key)
        return response['Body'].read()

    def get_user_cv(self, username: str) -> bytes:
        object_key = f'{self.ROOT}/{username}/cv.pdf'
        return self.get_object_bytes(object_key)

    def upload_user_cv(self, username: str, file_path: str) -> str:
        object_key = f'{self.ROOT}/{username}/cv.pdf'
        self.s3_client.upload_file(file_path, self.bucket_name, object_key)
        return object_key
