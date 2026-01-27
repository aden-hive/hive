"""
Input Sanitizer for security validation and data cleaning.

Provides comprehensive input sanitization to prevent:
- Code injection attacks
- XSS vulnerabilities  
- Path traversal
- Command injection
"""

import ast
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class SecurityViolation(RuntimeError):
    """Exception raised when a security violation is detected during sanitization."""
    
    def __init__(
        self,
        violation_type: str,
        field_path: str,
        description: str,
        severity: str,  # "low", "medium", "high", "critical"
        original_value: Any = None
    ):
        self.violation_type = violation_type
        self.field_path = field_path
        self.description = description
        self.severity = severity
        self.original_value = original_value
        super().__init__(f"{severity.upper()}: {description} (at {field_path})")


class InputSanitizer:
    """
    Comprehensive input sanitizer for security validation.
    
    Features:
    - Code injection detection using AST parsing
    - XSS pattern detection
    - Path traversal prevention
    - Command injection blocking
    - Size and complexity limits
    """

    def __init__(self):
        """Initialize the input sanitizer."""
        # Code injection patterns
        self._code_patterns = [
            # Python
            r'\bimport\s+\w+',
            r'\bfrom\s+\w+\s+import',
            r'\bdef\s+\w+\s*\(',
            r'\bclass\s+\w+\s*:',
            r'\bexec\s*\(',
            r'\beval\s*\(',
            r'\b__import__\s*\(',
            r'\basynchronous\s+def',
            r'\bawait\s+',
            r'\btry\s*:',
            r'\bexcept\s+',
            r'\bfinally\s*:',
            # JavaScript
            r'\bfunction\s+\w+\s*\(',
            r'\bconst\s+\w+\s*=',
            r'\blet\s+\w+\s*=',
            r'\brequire\s*\(',
            r'\bexport\s+',
            r'\bimport\s+.*\bfrom\b',
            # Shell commands
            r'\brm\s+-rf',
            r'\bsudo\s+',
            r'\bchmod\s+',
            r'\bchown\s+',
            r'\bkill\s+',
            r'\bkillall\s+',
            # SQL injection
            r'\bSELECT\s+.*\bFROM\b',
            r'\bINSERT\s+INTO\b',
            r'\bUPDATE\s+.*\bSET\b',
            r'\bDELETE\s+FROM\b',
            r'\bDROP\s+TABLE\b',
            r'\bUNION\s+SELECT\b',
            # HTML/Script injection
            r'<script[^>]*>',
            r'</script>',
            r'<iframe[^>]*>',
            r'javascript:',
            r'vbscript:',
            r'onload\s*=',
            r'onerror\s*=',
            r'onclick\s*=',
        ]

        # Compile patterns for performance
        self._compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self._code_patterns]

        # XSS patterns
        self._xss_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'vbscript:',
            r'onload\s*=',
            r'onerror\s*=',
            r'onclick\s*=',
            r'onmouseover\s*=',
            r'onfocus\s*=',
            r'onblur\s*=',
            r'<iframe[^>]*>',
            r'<object[^>]*>',
            r'<embed[^>]*>',
            r'<link[^>]*>',
            r'<meta[^>]*>',
        ]

        # Path traversal patterns
        self._path_traversal_patterns = [
            r'\.\./',
            r'\.\.\\',
            r'%2e%2e%2f',
            r'%2e%2e\\',
            r'\.\.%2f',
            r'\.\.%5c',
            r'%2e%2e/',
            r'%2e%2e\\',
        ]

        # Compile all patterns
        self._xss_compiled = [re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in self._xss_patterns]
        self._path_compiled = [re.compile(pattern, re.IGNORECASE) for pattern in self._path_traversal_patterns]

        # Size limits
        self._max_string_length = 10000
        self._max_dict_size = 100  # Maximum number of keys
        self._max_list_size = 1000  # Maximum number of items
        self._max_nesting_depth = 10

    def sanitize_dict(self, data: Dict[str, Any], field_path: str = "") -> Dict[str, Any]:
        """
        Sanitize a dictionary recursively.
        
        Args:
            data: Dictionary to sanitize
            field_path: Current field path for error reporting
            
        Returns:
            Sanitized dictionary
            
        Raises:
            SecurityViolation: If critical security violations are found
        """
        if not isinstance(data, dict):
            raise SecurityViolation(
                violation_type="type_error",
                field_path=field_path,
                description="Expected dict, got {}".format(type(data).__name__),
                severity="critical",
                original_value=data
            )

        if len(data) > self._max_dict_size:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"Dictionary too large: {len(data)} > {self._max_dict_size}",
                severity="high",
                original_value=data
            )

        sanitized = {}
        violations = []

        for key, value in data.items():
            current_path = f"{field_path}.{key}" if field_path else key
            
            try:
                # Sanitize key
                sanitized_key = self._sanitize_string(key, f"{current_path}.key")
                if sanitized_key != key:
                    logger.warning(f"Key sanitized: {key} -> {sanitized_key}")
                
                # Sanitize value based on type
                sanitized_value = self._sanitize_value(value, current_path)
                sanitized[sanitized_key] = sanitized_value
                
            except SecurityViolation as e:
                if e.severity == "critical":
                    raise
                violations.append(e)
                logger.warning(f"Security violation in {current_path}: {e.description}")

        # Log non-critical violations
        if violations:
            logger.warning(f"Found {len(violations)} non-critical security violations")

        return sanitized

    def _sanitize_value(self, value: Any, field_path: str) -> Any:
        """Sanitize a value based on its type."""
        if isinstance(value, str):
            return self._sanitize_string(value, field_path)
        elif isinstance(value, dict):
            return self.sanitize_dict(value, field_path)
        elif isinstance(value, list):
            return self._sanitize_list(value, field_path)
        elif isinstance(value, (int, float, bool)):
            return value
        elif value is None:
            return None
        else:
            # Convert unknown types to string and sanitize
            logger.warning(f"Unknown type {type(value).__name__} at {field_path}, converting to string")
            return self._sanitize_string(str(value), field_path)

    def _sanitize_string(self, value: str, field_path: str) -> str:
        """Sanitize a string value."""
        if len(value) > self._max_string_length:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"String too long: {len(value)} > {self._max_string_length}",
                severity="high",
                original_value=value
            )

        sanitized = value

        # Check for code injection
        code_violations = self._check_code_injection(sanitized, field_path)
        if code_violations:
            # For code injection, we're more strict - remove the content
            sanitized = "[CODE_CONTENT_REMOVED]"
            for violation in code_violations:
                if violation.severity == "critical":
                    raise violation

        # Check for XSS
        xss_violations = self._check_xss(sanitized, field_path)
        if xss_violations:
            # Remove XSS content
            for pattern in self._xss_compiled:
                sanitized = pattern.sub("[XSS_CONTENT_REMOVED]", sanitized)

        # Check for path traversal
        path_violations = self._check_path_traversal(sanitized, field_path)
        if path_violations:
            # Normalize path
            try:
                if '/' in sanitized or '\\' in sanitized:
                    # Try to normalize as a path
                    path_obj = Path(sanitized)
                    sanitized = str(path_obj.resolve())
            except (ValueError, OSError):
                # If path normalization fails, remove suspicious content
                for pattern in self._path_compiled:
                    sanitized = pattern.sub("", sanitized)

        return sanitized

    def _sanitize_list(self, value: List[Any], field_path: str) -> List[Any]:
        """Sanitize a list value."""
        if len(value) > self._max_list_size:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"List too large: {len(value)} > {self._max_list_size}",
                severity="high",
                original_value=value
            )

        sanitized = []
        violations = []

        for i, item in enumerate(value):
            current_path = f"{field_path}[{i}]"
            
            try:
                sanitized_item = self._sanitize_value(item, current_path)
                sanitized.append(sanitized_item)
            except SecurityViolation as e:
                if e.severity == "critical":
                    raise
                violations.append(e)
                logger.warning(f"Security violation in {current_path}: {e.description}")

        return sanitized

    def _check_code_injection(self, value: str, field_path: str) -> List[SecurityViolation]:
        """Check for code injection patterns."""
        violations = []

        # First, try AST parsing for Python code
        try:
            ast.parse(value)
            # If parsing succeeds, it might be valid Python code
            violations.append(SecurityViolation(
                violation_type="code_injection",
                field_path=field_path,
                description="String appears to be valid Python code",
                severity="high",
                original_value=value
            ))
        except SyntaxError:
            # Not valid Python code, continue with pattern checks
            pass

        # Check against patterns
        for pattern in self._compiled_patterns:
            if pattern.search(value):
                violations.append(SecurityViolation(
                    violation_type="code_injection",
                    field_path=field_path,
                    description=f"Code injection pattern detected: {pattern.pattern}",
                    severity="medium",
                    original_value=value
                ))

        return violations

    def _check_xss(self, value: str, field_path: str) -> List[SecurityViolation]:
        """Check for XSS patterns."""
        violations = []

        for pattern in self._xss_compiled:
            if pattern.search(value):
                violations.append(SecurityViolation(
                    violation_type="xss",
                    field_path=field_path,
                    description=f"XSS pattern detected: {pattern.pattern}",
                    severity="high",
                    original_value=value
                ))

        return violations

    def _check_path_traversal(self, value: str, field_path: str) -> List[SecurityViolation]:
        """Check for path traversal patterns."""
        violations = []

        for pattern in self._path_compiled:
            if pattern.search(value):
                violations.append(SecurityViolation(
                    violation_type="path_traversal",
                    field_path=field_path,
                    description=f"Path traversal pattern detected: {pattern.pattern}",
                    severity="medium",
                    original_value=value
                ))

        return violations

    def validate_file_path(self, file_path: str) -> bool:
        """
        Validate that a file path is safe and doesn't contain traversal.
        
        Args:
            file_path: File path to validate
            
        Returns:
            True if safe, False otherwise
        """
        try:
            # Normalize the path
            path_obj = Path(file_path).resolve()
            
            # Check if it tries to go outside current directory
            if '..' in Path(file_path).parts:
                return False
                
            # Check against traversal patterns
            for pattern in self._path_compiled:
                if pattern.search(file_path):
                    return False
                    
            return True
            
        except (ValueError, OSError):
            return False

    def sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a filename to prevent path traversal and injection.
        
        Args:
            filename: Filename to sanitize
            
        Returns:
            Sanitized filename
        """
        # Remove path separators
        sanitized = re.sub(r'[\\/]', '_', filename)
        
        # Remove dangerous characters
        sanitized = re.sub(r'[<>:"|?*]', '_', sanitized)
        
        # Remove control characters
        sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized)
        
        # Limit length
        if len(sanitized) > 255:
            sanitized = sanitized[:255]
            
        return sanitized or "unnamed_file"