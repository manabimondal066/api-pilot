const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"

export interface HealthResponse {
  status: string
  service: string
  version: string
  env: string
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/api/healthz`)
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }
  return response.json() as Promise<HealthResponse>
}
