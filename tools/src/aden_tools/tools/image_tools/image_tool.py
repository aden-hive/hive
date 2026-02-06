"""
Image Tool - Resize, compress, convert, and extract metadata from images.

Uses Pillow for image processing operations.
"""


from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

try:
    from PIL import Image
    from PIL import UnidentifiedImageError
    from PIL.ExifTags import TAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False



# Constants
MAX_FILE_SIZE_MB = 10
SUPPORTED_FORMATS = {"jpg", "jpeg", "png", "webp", "bmp", "gif"}



def register_tools(mcp: FastMCP) -> None:
    """Register Image tools with the MCP server."""


    # Early return if Pillow not available
    if not PILLOW_AVAILABLE:
        @mcp.tool()
        def image_resize(image_path: str, width: int, height: int) -> dict:
            """Pillow not installed."""
            return {
                "error": "Pillow not installed. Install with: pip install Pillow>=10.0.0"
            }
        @mcp.tool()
        def image_compress(image_path: str, quality: int = 75) -> dict:
            """Pillow not installed."""
            return {
                "error": "Pillow not installed. Install with: pip install Pillow>=10.0.0"
            }
        
        @mcp.tool()
        def image_convert(image_path: str, target_format: str) -> dict:
            """Pillow not installed."""
            return {
                "error": "Pillow not installed. Install with: pip install Pillow>=10.0.0"
            }
        
        @mcp.tool()
        def image_metadata(image_path: str) -> dict:
            """Pillow not installed."""
            return {
                "error": "Pillow not installed. Install with: pip install Pillow>=10.0.0"
            }
        
        return
        

    # Helper function for validation
    def _validate_image_file(image_path: str) -> dict | Path:
        """
        Validate image file and return Path if valid, error dict otherwise.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Path object if valid, error dict otherwise
        """
        try:
            path = Path(image_path).resolve()
            
            # Check existence
            if not path.exists():
                return {"error": f"Image file not found: {image_path}"}
            
            if not path.is_file():
                return {"error": f"Not a file: {image_path}"}
            
            # Validate extension
            if path.suffix.lower().lstrip(".") not in SUPPORTED_FORMATS:
                formats_str = ", ".join(sorted(SUPPORTED_FORMATS))
                return {
                    "error": f"Unsupported image format: {path.suffix}. Supported formats: {formats_str}"
                }
            
            # Check file size (max 10MB)
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                return {
                    "error": f"Image too large: {size_mb:.1f}MB "
                            f"(max {MAX_FILE_SIZE_MB}MB for memory safety)"
                }
            
            return path
            
        except PermissionError:
            return {"error": f"Permission denied: {image_path}"}
        except Exception as e:
            return {"error": f"Failed to validate image: {str(e)}"}



    @mcp.tool()
    def image_resize(
        image_path: str,
        width: int,
        height: int,
        maintain_aspect_ratio: bool = True,
        output_path: str | None = None,
    ) -> dict:
        """
        Resize an image to specified dimensions.
        
        Resizes images for thumbnails, web optimization, or standardized outputs.
        Optionally maintains aspect ratio to prevent distortion.
        
        Args:
            image_path: Path to the image file (absolute or relative)
            width: Target width in pixels (must be positive)
            height: Target height in pixels (must be positive)
            maintain_aspect_ratio: Keep original aspect ratio (default: True)
            output_path: Optional path to save resized image (auto-generated if None)
        
        Returns:
            Dict with resize results:
            - success: True if successful
            - path: Original file path
            - output_path: Path to resized image
            - original_size: [width, height] before resize
            - new_size: [width, height] after resize
            - file_size_kb: Output file size in KB
            
            Or error dict if failed:
            - error: Error message
        """
        
        # 1. Validate inputs
        validation = _validate_image_file(image_path)
        if isinstance(validation, dict):      # detect error 
            return validation
        
        path = validation
        
        if width <= 0 or height <= 0:
            return {"error": "Width and height must be positive integers."}
        if width > 10000 or height > 10000:
            return {"error": "Width and height must be less than 10,000 pixels for memory safety."}
        
        # 2. Open image
        try:
            with Image.open(path) as img:
                original_size = img.size     # (width, height)

                # 3. Resize image
                if maintain_aspect_ratio:
                    img.thumbnail((width, height), Image.Resampling.LANCZOS)
                    resized_img = img
                else:
                    resized_img = img.resize((width, height), Image.Resampling.LANCZOS)

                # 4. Save resized image
                out_path = Path(output_path) if output_path is not None else path.with_name(f"{path.stem}_resized{path.suffix}")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                resized_img.save(out_path)

                # Get file size
                file_size_kb = round(out_path.stat().st_size / 1024, 2)
 
                 # 5. Return result
                return {
                    "success": True,
                    "path": str(path),
                    "output_path": str(out_path),
                    "original_size": list(original_size),
                    "new_size": list(resized_img.size),
                    "file_size_kb": file_size_kb,
                }
        except UnidentifiedImageError:
            return {"error": f"Cannot identify image file: {image_path}"}
        except PermissionError:
            return {"error": f"Permission denied: {image_path}"}
        except Exception as e:
            return {"error": f"Failed to resize image: {str(e)}"}
        
        
    @mcp.tool()
    def image_compress(
        image_path: str,        # Path to the image file to compress
        quality: int = 75,      # Compression quality (1-95, higher is better quality)
        output_path: str | None = None,  # Optional path to save the compressed image
    ) -> dict:
        """
        Compress image file size by adjusting quality.
        
        Reduces file size while maintaining visual quality. Supports JPEG, PNG, and WebP.
        JPEG/WebP: quality directly controls compression. PNG: quality mapped to compression level.
        
        Args:
            image_path: Path to the image file (absolute or relative)
            quality: Compression quality (10-95, higher = better quality, default: 75)
            output_path: Optional path to save compressed image (auto-generated if None)
        
        Returns:
            Dict with compression results:
            - success: True if successful
            - path: Original file path
            - output_path: Path to compressed image
            - original_kb: Original file size in KB
            - compressed_kb: Compressed file size in KB
            - reduction_percent: Percentage reduction in file size
            
            Or error dict if failed:
            - error: Error message
        """

        # Validate file
        validation = _validate_image_file(image_path)
        if isinstance(validation, dict):
            return validation
        
        path = validation


        
        # Validate quality
        if not (10 <= quality <= 95):
            return {"error": "Quality must be between 10 and 95"}
        
        try:
            with Image.open(path) as img:
                
                if output_path is None:
                    output_path = str(path.with_name(
                        f"{path.stem}_compressed{path.suffix}"
                    ))

                # Get format
                fmt = (img.format or path.suffix.lstrip(".")).lower()

                # Determine output path
                out_path = Path(output_path) if output_path is not None else path.with_name(f"{path.stem}_compressed{path.suffix}")
                out_path.parent.mkdir(parents=True, exist_ok=True)

                # Compress based on format
                if fmt in ("jpg", "jpeg"):
                    # Convert RGBA to RGB for JPEG (no alpha channel)
                    if img.mode in ("RGBA", "LA", "P"):
                        rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode == "P":
                            img = img.convert("RGBA")
                        rgb_img.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                        img = rgb_img
                    img.save(out_path, "JPEG", quality=quality, optimize=True)

                elif fmt == "png":
                    # Map quality (10-95) to compress_level (9-0)
                    # Higher quality = lower compression level
                    compress_level = max(0, min(9, int((95 - quality) / 10)))
                    img.save(out_path, "PNG", optimize=True, compress_level=compress_level)

                elif fmt == "webp":
                    img.save(out_path, "WEBP", quality=quality, method=6)

                else:
                    # For other formats, just save with optimize
                    img.save(out_path, img.format, optimize=True)
            # Calculate sizes
            original_kb = round(path.stat().st_size / 1024, 2)
            compressed_kb = round(out_path.stat().st_size / 1024, 2)
            reduction = round(((original_kb - compressed_kb) / original_kb) * 100, 2) if original_kb > 0 else 0.0
            return {
                "success": True,
                "input_path": str(image_path),
                "output_path": str(out_path),
                "original_kb": original_kb,
                "compressed_kb": compressed_kb,
                "reduction_percent": reduction,
            }
        except UnidentifiedImageError:
            return {"error": f"Cannot identify image file: {image_path}"}
        except PermissionError:
            return {"error": f"Permission denied: {image_path}"}
        except Exception as e:
            return {"error": f"Failed to compress image: {str(e)}"}
        

    @mcp.tool()
    def image_convert(
        image_path: str,
        target_format: str,
        output_path: str | None = None,
    ) -> dict:
        """
        Convert image to a different format.
        
        Converts between PNG, JPG, WebP, and other common formats.
        Useful for web optimization (e.g., PNG → WebP) or compatibility (e.g., WebP → JPG).
        
        Args:
            image_path: Path to the image file (absolute or relative)
            target_format: Target format (png, jpg, jpeg, webp, bmp, gif)
            output_path: Optional path to save converted image (auto-generated if None)
        
        Returns:
            Dict with conversion results:
            - success: True if successful
            - input_path: Original file path
            - output_path: Path to converted image
            - original_format: Original image format
            - new_format: Target image format
            - file_size_kb: Output file size in KB
            
            Or error dict if failed:
            - error: Error message
        """

        # Validate file
        validation = _validate_image_file(image_path)
        if isinstance(validation, dict):
            return validation
        
        path = validation
        
        # Validate target format
        target_format = target_format.lower().lstrip(".")
        if target_format not in SUPPORTED_FORMATS:
            formats_str = ", ".join(sorted(f.lstrip(".") for f in SUPPORTED_FORMATS))
            return {
                "error": f"Unsupported target format: {target_format}. "
                        f"Supported: {formats_str}"
            }
        
        try:
            with Image.open(path) as img:
                original_format = img.format or path.suffix.lstrip(".")

                # Determine output path
                out_path = Path(output_path) if output_path is not None else path.with_suffix(f".{target_format}")
                out_path.parent.mkdir(parents=True, exist_ok=True)

                # Handle format-specific conversions
                if target_format in ("jpg", "jpeg"):
                    # Convert RGBA to RGB for JPEG
                    if img.mode in ("RGBA", "LA", "P"):
                        rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode == "P":
                            img = img.convert("RGBA")
                        rgb_img.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                        img = rgb_img
                    img.save(out_path, "JPEG", quality=85, optimize=True)
                    
                elif target_format == "png":
                    img.save(out_path, "PNG", optimize=True)
                    
                elif target_format == "webp":
                    img.save(out_path, "WEBP", quality=85, method=6)
                    
                else:
                    # For other formats
                    img.save(out_path, target_format.upper())
            
            # Get file size
            file_size_kb = round(out_path.stat().st_size / 1024, 2)
            
            return {
                "success": True,
                "path": str(path),
                "output_path": str(out_path),
                "original_format": original_format,
                "new_format": target_format,
                "file_size_kb": file_size_kb,
            }
            
        except UnidentifiedImageError:
            return {"error": f"Cannot identify image file: {image_path}"}
        except PermissionError:
            return {"error": f"Permission denied: {image_path}"}
        except Exception as e:
            return {"error": f"Failed to convert image: {str(e)}"}

                


    @mcp.tool()
    def image_metadata(
        image_path: str,
        include_exif: bool = True,
    ) -> dict:
        """
        Extract image metadata and EXIF information.
        
        Returns basic metadata (format, dimensions, file size) and optionally EXIF data
        (camera info, GPS coordinates, timestamps) if available.
        
        Args:
            image_path: Path to the image file (absolute or relative)
            include_exif: Include EXIF data if available (default: True)
        
        Returns:
            Dict with metadata:
            - success: True if successful
            - path: Image path
            - format: Image format (JPEG, PNG, etc.)
            - mode: Color mode (RGB, RGBA, etc.)
            - size: [width, height] in pixels
            - file_size_kb: File size in KB
            - exif: EXIF data dict (if include_exif=True and available)
            
            Or error dict if failed:
            - error: Error message
        """
        # Validate file
        validation = _validate_image_file(image_path)
        if isinstance(validation, dict):
            return validation
        
        path = validation
        
        try:
            with Image.open(path) as img:
                # Basic metadata
                file_size_kb = round(path.stat().st_size / 1024, 2)
                
                result: dict[str, Any] = {
                    "success": True,
                    "path": str(path),
                    "format": img.format,
                    "mode": img.mode,
                    "size": list(img.size),  # [width, height]
                    "file_size_kb": file_size_kb,
                }

                # Add PIL info dict (format-specific metadata)
                if img.info:
                    result["info"] = {k: str(v) for k, v in img.info.items()}

                # Extract EXIF data if requested
                if include_exif:
                    try:
                        exif_data = img.getexif()
                        if exif_data:
                            exif_dict = {}
                            for tag_id, value in exif_data.items():
                                tag_name = TAGS.get(tag_id, f"Tag{tag_id}")
                                # Convert value to string for JSON safety
                                exif_dict[tag_name] = str(value)
                            
                            if exif_dict:
                                result["exif"] = exif_dict
                    except Exception:
                        # Silently skip EXIF if not available or error
                        pass
                
                return result
                
        except UnidentifiedImageError:
            return {"error": f"Cannot identify image file: {image_path}"}
        except PermissionError:
            return {"error": f"Permission denied: {image_path}"}
        except Exception as e:
            return {"error": f"Failed to read image metadata: {str(e)}"}


