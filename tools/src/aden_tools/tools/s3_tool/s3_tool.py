"""
AWS S3 Tool for Hive Framework

Cloud object storage integration providing file upload, download, 
listing, and management operations.
"""

import os
import json
import logging
import io
import base64
from typing import Optional, Dict, Any, Union

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
from fastmcp import FastMCP

# Optional import for credential store
try:
    from aden_tools.credentials import CredentialStoreAdapter
    CREDENTIALS_AVAILABLE = True
except ImportError:
    CREDENTIALS_AVAILABLE = False
    CredentialStoreAdapter = None  # type: ignore

logger = logging.getLogger(__name__)


class S3Storage:
    """
    AWS S3 storage handler with retry logic and error handling.
    Supports IAM roles, environment variables, and credential store.
    """
    
    def __init__(
        self,
        region: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        session_token: Optional[str] = None,
        credentials: Optional[Any] = None
    ):
        boto_config = Config(
            retries=dict(max_attempts=3, mode='adaptive'),
            connect_timeout=10,
            read_timeout=30
        )
        
        client_kwargs = {
            'region_name': region or os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
            'config': boto_config
        }
        
        # Try credentials adapter first (only if available)
        if CREDENTIALS_AVAILABLE and credentials:
            try:
                creds = credentials.get_credentials("aws")
                client_kwargs['aws_access_key_id'] = creds['access_key_id']
                client_kwargs['aws_secret_access_key'] = creds['secret_access_key']
                if creds.get('session_token'):
                    client_kwargs['aws_session_token'] = creds['session_token']
            except Exception:
                pass
        
        # Fall back to parameters or env vars
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
        data: Union[bytes, str],
        metadata: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload file to S3 bucket."""
        try:
            extra_args = {}
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
        version_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Download file from S3 bucket."""
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
    ) -> Dict[str, Any]:
        """List objects in S3 bucket."""
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
        version_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete object from S3 bucket."""
        try:
            args = {'Bucket': bucket, 'Key': key}
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


def register_tools(
    mcp: FastMCP,
    credentials: Optional[Any] = None
) -> None:
    """
    Register S3 tools with MCP server.
    
    Args:
        mcp: FastMCP server instance
        credentials: Optional CredentialStoreAdapter for AWS credentials
    """
    
    storage = S3Storage(
        region=os.getenv('AWS_DEFAULT_REGION'),
        access_key=os.getenv('AWS_ACCESS_KEY_ID'),
        secret_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        session_token=os.getenv('AWS_SESSION_TOKEN'),
        credentials=credentials
    )

    @mcp.tool()
    def s3_upload(
        bucket: str,
        key: str,
        data: str,
        metadata: Optional[str] = None,
        content_type: Optional[str] = None,
        base64_encoded: bool = False
    ) -> str:
        """
        Upload data to S3 bucket.
        
        Args:
            bucket: S3 bucket name
            key: Object key (file path)
            data: Content to upload
            metadata: JSON string with metadata key-value pairs
            content_type: MIME type
            base64_encoded: Whether data is base64 encoded
            
        Returns:
            JSON string with upload result
        """
        try:
            meta_dict = json.loads(metadata) if metadata else None
            
            if base64_encoded:
                data_bytes = base64.b64decode(data)
            else:
                data_bytes = data.encode('utf-8')
            
            result = storage.upload_file(
                bucket=bucket,
                key=key,
                data=data_bytes,
                metadata=meta_dict,
                content_type=content_type
            )
            return json.dumps(result, default=str)
        except Exception as e:
            logger.error(f"s3_upload error: {e}")
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def s3_download(
        bucket: str,
        key: str,
        version_id: Optional[str] = None
    ) -> str:
        """
        Download file from S3 bucket.
        
        Args:
            bucket: S3 bucket name
            key: Object key
            version_id: Specific version to download
            
        Returns:
            JSON string with file content and metadata
        """
        try:
            result = storage.download_file(bucket, key, version_id)
            return json.dumps(result, default=str)
        except Exception as e:
            logger.error(f"s3_download error: {e}")
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def s3_list(
        bucket: str,
        prefix: str = "",
        max_keys: int = 100
    ) -> str:
        """
        List objects in S3 bucket.
        
        Args:
            bucket: S3 bucket name
            prefix: Filter by key prefix
            max_keys: Maximum objects to return
            
        Returns:
            JSON string with objects and folders list
        """
        try:
            result = storage.list_objects(bucket, prefix, max_keys)
            return json.dumps(result, default=str)
        except Exception as e:
            logger.error(f"s3_list error: {e}")
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def s3_delete(
        bucket: str,
        key: str,
        version_id: Optional[str] = None
    ) -> str:
        """
        Delete object from S3 bucket.
        
        Args:
            bucket: S3 bucket name
            key: Object key to delete
            version_id: Specific version to delete
            
        Returns:
            JSON string with deletion status
        """
        try:
            result = storage.delete_object(bucket, key, version_id)
            return json.dumps(result, default=str)
        except Exception as e:
            logger.error(f"s3_delete error: {e}")
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def s3_check_credentials() -> str:
        """
        Check if AWS credentials are configured correctly.
        
        Returns:
            JSON string with credential status
        """
        try:
            session = boto3.Session()
            sts = session.client('sts')
            identity = sts.get_caller_identity()
            return json.dumps({
                "success": True,
                "configured": True,
                "account": identity.get('Account'),
                "arn": identity.get('Arn'),
                "user_id": identity.get('UserId')
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "configured": False,
                "message": str(e)
            })