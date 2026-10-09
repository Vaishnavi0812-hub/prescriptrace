export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

export interface Health {
  status: "ok" | "degraded";
  database: boolean;
  datasets_loaded: number;
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) {
    throw new Error(`${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export const fetchHealth = (signal?: AbortSignal): Promise<Health> =>
  getJson<Health>("/api/v1/health", signal);
