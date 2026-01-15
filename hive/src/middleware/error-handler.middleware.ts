/**
 * Global Error Handler Middleware
 *
 * Handles all errors and sends consistent JSON responses.
 */

import { Request, Response, NextFunction } from 'express';

interface HttpError extends Error {
  status?: number;
  statusCode?: number;
}

/**
 * Error handler middleware
 * @param {Error} err - Error object
 * @param {Object} req - Express request
 * @param {Object} res - Express response
 * @param {Function} next - Next middleware
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function errorHandler(err: HttpError, req: Request, res: Response, _next: NextFunction): void {
  // Log error
  console.error('[Error]', {
    message: err.message,
    status: err.status || err.statusCode || 500,
    path: req.path,
    method: req.method,
    stack: process.env.NODE_ENV === 'development' ? err.stack : undefined,
  });

  // Get status code
  const status = err.status || err.statusCode || 500;

  // Send error response
  res.status(status).json({
    error: err.name || 'Error',
    message: err.message || 'An unexpected error occurred',
    status,
    ...(process.env.NODE_ENV === 'development' && { stack: err.stack }),
  });
}

export { errorHandler };
