"""
Simple test for S3 Tool - runs without pytest
"""

import sys
import os
import asyncio

# Add the s3_tool directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import directly from the module file
from s3_tool import S3Storage, register_tools
from fastmcp import FastMCP

# Mock AWS with moto
from moto import mock_aws
import boto3
import json

print("Testing S3 Tool...")

@mock_aws
def test_upload_download():
    print("Test 1: Upload and Download")
    storage = S3Storage(region="us-east-1")
    storage.client.create_bucket(Bucket="test-bucket")
    
    result = storage.upload_file(bucket="test-bucket", key="test.txt", data=b"Hello World")
    assert result['success'], f"Upload failed: {result}"
    
    download = storage.download_file(bucket="test-bucket", key="test.txt")
    assert download['success'], f"Download failed: {download}"
    assert download['content'] == "Hello World", "Content mismatch"
    
    print("✓ Upload/Download test passed")

@mock_aws
def test_list():
    print("Test 2: List Objects")
    storage = S3Storage(region="us-east-1")
    storage.client.create_bucket(Bucket="test-bucket")
    storage.upload_file(bucket="test-bucket", key="file1.txt", data=b"content1")
    storage.upload_file(bucket="test-bucket", key="file2.txt", data=b"content2")
    
    result = storage.list_objects(bucket="test-bucket")
    assert result['success'], f"List failed: {result}"
    assert len(result['objects']) == 2, f"Expected 2 objects, got {len(result['objects'])}"
    
    print("✓ List test passed")

@mock_aws
def test_mcp_tools():
    print("Test 3: MCP Tools")
    
    async def async_test():
        mcp = FastMCP("test")
        register_tools(mcp)
        
        client = boto3.client('s3', region_name='us-east-1')
        client.create_bucket(Bucket='test-bucket')
        
        # Get the tool (this is async)
        tool = await mcp.get_tool('s3_upload')
        result_text = tool.fn(bucket="test-bucket", key="mcp-test.txt", data="MCP Test")
        result_dict = json.loads(result_text)
        assert result_dict['success'], f"MCP upload failed: {result_dict}"
    
    # Run the async test
    asyncio.run(async_test())
    print("✓ MCP Tools test passed")

if __name__ == "__main__":
    try:
        test_upload_download()
        test_list()
        test_mcp_tools()
        print("\n✅ All tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()