"""
Middleware for Policy Server

Handles cross-cutting concerns like:
- Correlation ID tracking
- Request logging
- Error handling
"""

import time
import uuid
import logging
from typing import Callable, Optional
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable to store correlation ID for current request
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)

logger = logging.getLogger(__name__)


def generate_correlation_id() -> str:
    """Generate a new correlation ID"""
    timestamp = int(time.time())
    random_id = uuid.uuid4().hex[:12]
    return f"echo-{timestamp}-{random_id}"


def get_correlation_id() -> Optional[str]:
    """Get the current request's correlation ID"""
    return correlation_id_ctx.get()


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract or generate correlation IDs for request tracking.
    
    Checks for X-Correlation-ID header, generates one if missing.
    Stores in context variable for use throughout request lifecycle.
    Adds to response headers for client tracking.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract or generate correlation ID
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            correlation_id = generate_correlation_id()
        
        # Store in context variable
        token = correlation_id_ctx.set(correlation_id)
        
        # Log request start
        logger.info(
            f"[{correlation_id}] {request.method} {request.url.path}",
            extra={"correlation_id": correlation_id, "method": request.method, "path": request.url.path}
        )
        
        start_time = time.time()
        
        try:
            # Process request
            response = await call_next(request)
            
            # Add correlation ID to response headers
            response.headers["X-Correlation-ID"] = correlation_id
            
            # Log request completion
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"[{correlation_id}] {request.method} {request.url.path} - {response.status_code} ({duration_ms}ms)",
                extra={
                    "correlation_id": correlation_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms
                }
            )
            
            return response
            
        except Exception as e:
            # Log error with correlation ID
            logger.error(
                f"[{correlation_id}] Error processing request: {str(e)}",
                extra={"correlation_id": correlation_id},
                exc_info=True
            )
            raise
        
        finally:
            # Reset context variable
            correlation_id_ctx.reset(token)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all requests with timing information.
    Works in conjunction with CorrelationIDMiddleware.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        correlation_id = get_correlation_id() or "no-correlation-id"
        
        # Log request body for POST/PUT (with size limit)
        if request.method in ["POST", "PUT", "PATCH"]:
            # Don't log body for large payloads or file uploads
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    # Note: This consumes the body stream, so we'd need to handle carefully
                    # For now, just log that we have a JSON payload
                    logger.debug(f"[{correlation_id}] Request has JSON payload")
                except Exception:
                    pass
        
        response = await call_next(request)
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Log slow requests as warnings
        if duration_ms > 1000:
            logger.warning(
                f"[{correlation_id}] SLOW REQUEST: {request.method} {request.url.path} took {duration_ms}ms",
                extra={
                    "correlation_id": correlation_id,
                    "duration_ms": duration_ms,
                    "slow_request": True
                }
            )
        
        return response
