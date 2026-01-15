// In the honeycomb monorepo, hive handles all endpoints (auth, user, IAM, and agent control)
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

// Main API client for all hive endpoints
export const apiClient = new ApiClient(API_URL)

// Aliases for compatibility with existing code
export const serverClient = apiClient
export const hiveClient = apiClient
