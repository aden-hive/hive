from __future__ import annotations

import base64
import io
import json
import logging
import os
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)


class S3Storage:
    def __init__(
        self,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        session_token: str | None = None,
    ):
        boto_config = Config(
            retries=dict(max_attempts=3, mode='adaptive'),
            connect_timeout=10,
            read_timeout=30
        )
        
        client_kwargs: dict[str, Any] = {
            'region_name': region or os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
            'config': boto_config
        }
        
        if access_key and secret_key:
            client_kwargs['aws_access_key_id'] = access_key
            client_kwargs['aws_secret_access_key'] = secret_key
            if session_token:
                client_kwargs['aws_session_token'] = session_token
                
        self.client = boto3.client('s3', **client_kwargs)
    
    def upload_file(
        self,
        bucket: str,
        key: str,
        data: bytes | str,
        metadata: dict[str, str] | None = None,
        content_type: str | None = None
    ) -> dict[str, Any]:
        try:
            extra_args: dict[str, Any] = {}
            if metadata:
                extra_args['Metadata'] = metadata
            if content_type:
                extra_args['ContentType'] = content_type
            
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            file_obj = io.BytesIO(data)
            self.client.upload_fileobj(file_obj, bucket, key, ExtraArgs=extra_args)
            
            head = self.client.head_object(Bucket=bucket, Key=key)
            return {
                "success": True,
                "bucket": bucket,
                "key": key,
                "etag": head.get('ETag'),
                "version_id": head.get('VersionId'),
                "content_length": head.get('ContentLength')
            }
        except ClientError as e:
            return {
                "success": False,
                "error": e.response['Error']['Code'],
                "message": e.response['Error']['Message']
            }
    
    def download_file(
        self,
        bucket: str,
        key: str,
        version_id: str | None = None
    ) -> dict[str, Any]:
        try:
            extra_args = {'VersionId': version_id} if version_id else {}
            file_obj = io.BytesIO()
            self.client.download_fileobj(bucket, key, file_obj, ExtraArgs=extra_args)
            file_obj.seek(0)
            content = file_obj.read()
            
            try:
                content_str = content.decode('utf-8')
                return {
                    "success": True,
                    "content": content_str,
                    "bucket": bucket,
                    "key": key,
                    "content_length": len(content)
                }
            except UnicodeDecodeError:
                return {
                    "success": True,
                    "content_base64": base64.b64encode(content).decode('utf-8'),
                    "bucket": bucket,
                    "key": key,
                    "content_length": len(content)
                }
        except ClientError as e:
            return {
                "success": False,
                "error": e.response['Error']['Code'],
                "message": e.response['Error']['Message']
            }
    
    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        max_keys: int = 1000
    ) -> dict[str, Any]:
        try:
            paginator = self.client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=bucket,
                Prefix=prefix,
                Delimiter="/",
                PaginationConfig={'MaxItems': max_keys}
            )
            
            objects = []
            prefixes = []
            for page in page_iterator:
                for obj in page.get('Contents', []):
                    objects.append({
                        "key": obj['Key'],
                        "size": obj['Size'],
                        "last_modified": obj['LastModified'].isoformat(),
                        "etag": obj['ETag']
                    })
                for pref in page.get('CommonPrefixes', []):
                    prefixes.append(pref['Prefix'])
            
            return {
                "success": True,
                "bucket": bucket,
                "objects": objects,
                "folders": prefixes,
                "total_count": len(objects)
            }
        except ClientError as e:
            return {
                "success": False,
                "error": e.response['Error']['Code'],
                "message": e.response['Error']['Message']
            }
    
    def delete_object(
        self,
        bucket: str,
        key: str,
        version_id: str | None = None
    ) -> dict[str, Any]:
        try:
            args: dict[str, Any] = {'Bucket': bucket, 'Key': key}
            if version_id:
                args['VersionId'] = version_id
            response = self.client.delete_object(**args)
            return {
                "success": True,
                "bucket": bucket,
                "key": key,
                "delete_marker": response.get('DeleteMarker', False)
            }
        except ClientError as e:
            return {
                "success": False,
                "error": e.response['Error']['Code'],
                "message": e.response['Error']['Message']
            }


def _get_s3_client(credentials: CredentialStoreAdapter | None = None) -> S3Storage | dict[str, Any]:
    if credentials:
        try:
            access_key = credentials.get("aws_access_key_id")
            secret_key = credentials.get("aws_secret_access_key")
            session_token = credentials.get("aws_session_token")
            region = credentials.get("aws_region")
            
            if access_key and secret_key:
                return S3Storage(
                    region=region,
                    access_key=access_key,
                    secret_key=secret_key,
                    session_token=session_token
                )
        except Exception as e:
            logger.warning("Credential adapter failed, falling back to env vars: %s", e)

    region = os.getenv("AWS_DEFAULT_REGION")
    access_key = os.getenv('AWS_ACCESS_KEY_ID')
    secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    session_token = os.getenv('AWS_SESSION_TOKEN')
    
    if not access_key or not secret_key:
        return {
            "error": "AWS credentials not configured",
            "help": "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables, or configure credentials in the credential store.",
            "success": False
        }
    
    return S3Storage(
        region=region,
        access_key=access_key,
        secret_key=secret_key,
        session_token=session_token
    )


def register_tools(mcp: Any, credentials: CredentialStoreAdapter | None = None) -> None:
    
    @mcp.tool()
    def s3_upload(
        bucket: str,
        key: str,
        data: str,
        metadata: str | None = None,
        content_type: str | None = None,
        base64_encoded: bool = False
    ) -> dict[str, Any]:
        storage = _get_s3_client(credentials)
        if isinstance(storage, dict) and not storage.get("success", True):
            return storage
        
        try:
            meta_dict = json.loads(metadata) if metadata else None
            
            if base64_encoded:
                data_bytes = base64.b64decode(data)
            else:
                data_bytes = data.encode('utf-8')
            
            return storage.upload_file(
                bucket=bucket,
                key=key,
                data=data_bytes,
                metadata=meta_dict,
                content_type=content_type
            )
        except Exception as e:
            logger.error(f"s3_upload error: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def s3_download(
        bucket: str,
        key: str,
        version_id: str | None = None
    ) -> dict[str, Any]:
        storage = _get_s3_client(credentials)
        if isinstance(storage, dict) and not storage.get("success", True):
            return storage
        
        try:
            return storage.download_file(bucket, key, version_id)
        except Exception as e:
            logger.error(f"s3_download error: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def s3_list(
        bucket: str,
        prefix: str = "",
        max_keys: int = 100
    ) -> dict[str, Any]:
        storage = _get_s3_client(credentials)
        if isinstance(storage, dict) and not storage.get("success", True):
            return storage
        
        try:
            return storage.list_objects(bucket, prefix, max_keys)
        except Exception as e:
            logger.error(f"s3_list error: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def s3_delete(
        bucket: str,
        key: str,
        version_id: str | None = None
    ) -> dict[str, Any]:
        storage = _get_s3_client(credentials)
        if isinstance(storage, dict) and not storage.get("success", True):
            return storage

        try:
            return storage.delete_object(bucket, key, version_id)
        except Exception as e:
            logger.error("s3_delete error: %s", e)
            return {"success": False, "error": str(e)}
