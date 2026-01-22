/**
 * API Client Service
 *
 * Generic HTTP client for all hive endpoints (auth, user, IAM, and agent control).
 * Handles authentication tokens from localStorage and standard CRUD operations.
 */

const API_URL = import.meta.env.VITE_API_URL || ''


export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  private async parseErrorMessage(response: Response): Promise<string> {
    const text = await response.text()
    try {
      const json = JSON.parse(text)
      return json.msg || json.message || text
    } catch {
      return text
    }
  }

  private getHeaders(): HeadersInit {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    }
    const token = localStorage.getItem('token')
    if (token) headers['Authorization'] = token
    return headers
  }

  /**
   * Performs a GET request to the specified endpoint.
   * @template T - Expected response type
   * @param endpoint - API endpoint path (e.g., '/user/profile')
   * @returns Promise resolving to the parsed JSON response
   * @throws {ApiError} When the response status is not ok (non-2xx)
   */
  async get<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'GET',
      headers: this.getHeaders(),
    })

    if (!response.ok) {
      throw new ApiError(response.status, await this.parseErrorMessage(response))
    }

    return response.json()
  }

  /**
   * Performs a POST request to the specified endpoint.
   * @template T - Expected response type
   * @param endpoint - API endpoint path
   * @param data - Optional request body (will be JSON stringified)
   * @returns Promise resolving to the parsed JSON response
   * @throws {ApiError} When the response status is not ok (non-2xx)
   */
  async post<T>(endpoint: string, data?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: data ? JSON.stringify(data) : undefined,
    })

    if (!response.ok) {
      throw new ApiError(response.status, await this.parseErrorMessage(response))
    }

    return response.json()
  }

  /**
   * Performs a PUT request to the specified endpoint.
   * @template T - Expected response type
   * @param endpoint - API endpoint path
   * @param data - Request body (will be JSON stringified)
   * @returns Promise resolving to the parsed JSON response
   * @throws {ApiError} When the response status is not ok (non-2xx)
   */
  async put<T>(endpoint: string, data: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'PUT',
      headers: this.getHeaders(),
      body: JSON.stringify(data),
    })

    if (!response.ok) {
      throw new ApiError(response.status, await this.parseErrorMessage(response))
    }

    return response.json()
  }

  /**
   * Performs a DELETE request to the specified endpoint.
   * @template T - Expected response type
   * @param endpoint - API endpoint path
   * @returns Promise resolving to the parsed JSON response
   * @throws {ApiError} When the response status is not ok (non-2xx)
   */
  async delete<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'DELETE',
      headers: this.getHeaders(),
    })

    if (!response.ok) {
      throw new ApiError(response.status, await this.parseErrorMessage(response))
    }

    return response.json()
  }
}

/** Main API client instance for all hive endpoints. */
export const apiClient = new ApiClient(API_URL)

/** @deprecated Use apiClient instead. Alias for backward compatibility. */
export const serverClient = apiClient

/** @deprecated Use apiClient instead. Alias for backward compatibility. */
export const hiveClient = apiClient
