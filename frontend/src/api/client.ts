/**
 * API client for Teamarr backend.
 */

const API_BASE = "/api/v1"

export class ApiError extends Error {
  status: number
  statusText: string

  constructor(status: number, statusText: string, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.statusText = statusText
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text()
    let message = text
    try {
      const json = JSON.parse(text)
      // Handle FastAPI validation errors (detail is array of objects)
      if (Array.isArray(json.detail)) {
        message = json.detail
          .map((err: { msg?: string; loc?: string[] }) => {
            const field = err.loc?.slice(-1)[0] || "field"
            return `${field}: ${err.msg || "invalid"}`
          })
          .join(", ")
      } else {
        message = json.detail || json.message || text
      }
    } catch {
      // Use raw text
    }
    throw new ApiError(response.status, response.statusText, message)
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  return response.json()
}

export const api = {
  async get<T>(path: string): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`)
    return handleResponse<T>(response)
  },

  async post<T>(path: string, data?: unknown): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: data ? JSON.stringify(data) : undefined,
    })
    return handleResponse<T>(response)
  },

  async put<T>(path: string, data: unknown): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
    return handleResponse<T>(response)
  },

  async patch<T>(path: string, data?: unknown): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: data ? JSON.stringify(data) : undefined,
    })
    return handleResponse<T>(response)
  },

  async delete<T>(path: string): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "DELETE",
    })
    return handleResponse<T>(response)
  },
}

// Health check (outside /api/v1)
export async function checkHealth(): Promise<{ status: string }> {
  const response = await fetch("/health")
  return handleResponse(response)
}
