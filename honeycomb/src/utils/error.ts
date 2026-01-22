/**
 * Error handling utilities for type-safe error extraction.
 * Use these functions in catch blocks with `catch (err: unknown)`.
 */

/**
 * Safely extract error message from unknown error type.
 * Handles Error objects, string errors, and objects with message property.
 *
 * @example
 * try {
 *   await riskyOperation();
 * } catch (err: unknown) {
 *   console.error(getErrorMessage(err));
 * }
 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'string') {
    return error;
  }
  if (error && typeof error === 'object' && 'message' in error) {
    return String((error as { message: unknown }).message);
  }
  return 'Unknown error occurred';
}
