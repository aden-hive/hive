"""
Cloudinary media management tools.
"""

import cloudinary
import cloudinary.uploader
import cloudinary.api
from fastmcp import FastMCP
from typing import Any, Optional, Dict, List
import json
import logging

from ..credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)

def register_cloudinary(
    mcp: FastMCP,
    credentials: Optional[CredentialStoreAdapter] = None,
) -> None:
    """
    Register Cloudinary tools.
    """

    def _get_config():
        """Helper to get and validate Cloudinary config."""
        url = None
        if credentials:
            url = credentials.get("cloudinary")
        
        if not url:
            import os
            url = os.environ.get("CLOUDINARY_URL")
            
        if not url:
            raise ValueError(
                "Cloudinary credentials not found. Please set CLOUDINARY_URL environment variable."
            )
            
        # The library uses CLOUDINARY_URL environment variable by default
        # or we can explicitly configure it.
        cloudinary.config(cloudinary_url=url)
        return True

    @mcp.tool()
    def cloudinary_upload(
        file_path: str,
        public_id: Optional[str] = None,
        folder: Optional[str] = None,
        resource_type: str = "auto",
        transformation: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """
        Upload an image or video to Cloudinary.

        Args:
            file_path: Local path, URL, or base64 data to upload.
            public_id: Optional identifier for the asset.
            folder: Optional folder to store the asset in.
            resource_type: Type of asset ("image", "video", "raw", "auto").
            transformation: List of transformations to apply (e.g., [{"width": 500, "crop": "scale"}]).
            tags: Optional tags to associate with the asset.
        """
        _get_config()
        try:
            options = {
                "resource_type": resource_type,
            }
            if public_id:
                options["public_id"] = public_id
            if folder:
                options["folder"] = folder
            if transformation:
                options["transformation"] = transformation
            if tags:
                options["tags"] = tags

            result = cloudinary.uploader.upload(file_path, **options)
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error uploading to Cloudinary: {str(e)}"

    @mcp.tool()
    def cloudinary_transform(
        public_id: str,
        transformation: List[Dict[str, Any]],
        resource_type: str = "image",
        sign_url: bool = False,
    ) -> str:
        """
        Generate a transformed URL for an existing asset.

        Args:
            public_id: The public ID of the asset.
            transformation: List of transformations to apply.
            resource_type: Type of asset ("image", "video", "raw").
            sign_url: Whether to sign the URL (required for some restricted transformations).
        """
        _get_config()
        try:
            url, _ = cloudinary.utils.cloudinary_url(
                public_id,
                transformation=transformation,
                resource_type=resource_type,
                secure=True,
                sign_url=sign_url
            )
            return json.dumps({"transformed_url": url}, indent=2)
        except Exception as e:
            return f"Error transforming Cloudinary asset: {str(e)}"

    @mcp.tool()
    def cloudinary_get_asset(
        public_id: str,
        resource_type: str = "image",
        colors: bool = False,
        faces: bool = False,
    ) -> str:
        """
        Retrieve detailed metadata for an existing asset.

        Args:
            public_id: The public ID of the asset.
            resource_type: Type of asset ("image", "video", "raw").
            colors: Whether to include color information.
            faces: Whether to include face coordinates.
        """
        _get_config()
        try:
            result = cloudinary.api.resource(
                public_id,
                resource_type=resource_type,
                colors=colors,
                faces=faces
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error retrieving Cloudinary asset: {str(e)}"

    @mcp.tool()
    def cloudinary_delete(
        public_ids: List[str],
        resource_type: str = "image",
        invalidate: bool = True,
    ) -> str:
        """
        Delete one or more assets from Cloudinary.

        Args:
            public_ids: List of public IDs to delete.
            resource_type: Type of assets ("image", "video", "raw").
            invalidate: Whether to invalidate CDN cache for these assets.
        """
        _get_config()
        try:
            result = cloudinary.api.delete_resources(
                public_ids,
                resource_type=resource_type,
                invalidate=invalidate
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error deleting Cloudinary assets: {str(e)}"

    @mcp.tool()
    def cloudinary_list_assets(
        prefix: Optional[str] = None,
        max_results: int = 10,
        resource_type: str = "image",
        type: str = "upload",
    ) -> str:
        """
        List assets in a Cloudinary account.

        Args:
            prefix: Optional filter by public ID prefix.
            max_results: Maximum number of assets to return.
            resource_type: Type of assets ("image", "video", "raw").
            type: Storage type ("upload", "private", "authenticated").
        """
        _get_config()
        try:
            params = {
                "max_results": max_results,
                "resource_type": resource_type,
                "type": type
            }
            if prefix:
                params["prefix"] = prefix
                
            result = cloudinary.api.resources(**params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error listing Cloudinary assets: {str(e)}"
