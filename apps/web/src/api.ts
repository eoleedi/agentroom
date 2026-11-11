export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function request<T>(path: string, token = '', options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api${path}`, {...options, headers, cache: 'no-store'})
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    const detail = data?.detail
    throw new ApiError(response.status, typeof detail === 'string' ? detail : `Request failed (${response.status}).`)
  }
  return response.json() as Promise<T>
}

export function post<T>(path: string, body: unknown, token: string) {
  return request<T>(path, token, {method: 'POST', body: JSON.stringify(body)})
}

export const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`
export const errorText = (error: unknown) => error instanceof Error ? error.message : 'The request could not be completed.'
