const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: { error: string; type?: string; [key: string]: unknown },
  ) {
    super(body.error);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = isFormData
    ? {}  // Let browser set Content-Type with boundary for multipart
    : { "Content-Type": "application/json", ...options.headers as Record<string, string> };
  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ error: response.statusText }));
    throw new ApiError(response.status, body);
  }

  return response.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "DELETE",
      body: body ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    }),
  upload: <T>(path: string, formData: FormData) =>
    request<T>(path, { method: "POST", body: formData }),
};
