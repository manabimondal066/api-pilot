// Typed API client — hand-written to match backend app/schemas/api.py
// Will switch to OpenAPI generation in a later sprint once types start drifting.

export type Uuid = string;
export type IsoDateTime = string;
export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface EndpointOut {
  id: Uuid;
  method: HttpMethod;
  path: string;
  name: string;
  description: string | null;
}

export interface EndpointDetailOut extends EndpointOut {
  schema: Record<string, unknown>; // matches alias on backend
}

export interface SuiteSummaryOut {
  id: Uuid;
  name: string;
  spec_id: Uuid;
  generation_status: string;
  endpoint_count: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface SuiteDetailOut {
  id: Uuid;
  name: string;
  spec_id: Uuid;
  generation_status: string;
  // Auto-assigned for cURL imports; null for Swagger/Postman imports.
  environment_id: Uuid | null;
  endpoints: EndpointOut[];
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

// ---------------------------------------------------------------------------
// Tests (AI-generated)
// ---------------------------------------------------------------------------

export type TestCategory = "POSITIVE" | "NEGATIVE" | "EDGE";
export type ValidationSeverity = "CRITICAL" | "WARNING";
// Orthogonal to severity above — whether this validation's result is
// trusted enough to decide the test's overall verdict (Fix B). Optional:
// absent on any validation persisted before this feature existed, which
// must be treated the same as "enforced" (see the backend's defaulting
// accessor, app.services.validation_enforcement.get_enforcement).
export type ValidationEnforcement = "enforced" | "advisory";
export type ValidationGrounding = "spec" | "observed" | "inferred";

export interface ValidationOut {
  id: string;
  type: string;
  description: string; // human-readable, e.g. "Status code is 201"
  target: string | null;
  expected: unknown;
  severity: ValidationSeverity;
  enforcement?: ValidationEnforcement;
  grounding?: ValidationGrounding | null;
}

export interface ExtractionOut {
  name: string;
  source: string;
}

export interface TestOut {
  id: Uuid;
  suite_id: Uuid;
  endpoint_id: Uuid;
  name: string;
  category: TestCategory;
  method: HttpMethod;
  path: string;
  headers: Record<string, string>;
  query_params: Record<string, unknown>;
  body: unknown;
  validations: ValidationOut[];
  extractions: ExtractionOut[];
  depends_on: string[];
  confidence: number;
  ai_notes: string | null;
  created_by: string;
  version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

// ---------------------------------------------------------------------------
// Environments
// ---------------------------------------------------------------------------

export type EnvironmentAuthType = "none" | "bearer" | "basic" | "api_key";

export interface EnvironmentOut {
  id: Uuid;
  workspace_id: Uuid;
  name: string;
  base_url: string;
  auth_type: string;
  auth_config: Record<string, unknown>;
  default_headers: Record<string, string>;
  variables: Record<string, unknown>;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  // Computed server-side — true when auth_type is "none" (e.g. a cURL
  // import that had no Authorization header to draw from).
  is_incomplete: boolean;
}

export interface EnvironmentIn {
  name: string;
  base_url: string;
  auth_type: EnvironmentAuthType;
  auth_config: Record<string, unknown>;
  default_headers: Record<string, string>;
  variables?: Record<string, unknown>;
}

export type EnvironmentUpdateIn = Partial<EnvironmentIn>;

// ---------------------------------------------------------------------------
// Executions (deterministic test runs — no AI involved)
// ---------------------------------------------------------------------------

export type ExecutionResultStatus =
  | "passed"
  | "failed"
  | "inconclusive"
  | "error"
  | "skipped";
export type ExecutionStatus = "running" | "completed" | "error" | "skipped";

export interface ValidationResultOut {
  id: string | null;
  type: string | null;
  description: string | null;
  severity: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
  error?: string;
  // Absent on results recorded before this feature existed — treat as
  // "enforced" (same default the backend applies).
  enforcement?: ValidationEnforcement;
}

export interface RequestSnapshot {
  method: string;
  url: string;
  headers: Record<string, string>;
  params: Record<string, unknown>;
  body: unknown;
}

export interface ResponseSnapshot {
  status_code: number;
  headers: Record<string, string>;
  body: unknown;
}

export interface ExecutionResultOut {
  id: Uuid;
  execution_id: Uuid;
  test_id: Uuid;
  status: ExecutionResultStatus;
  request_snapshot: RequestSnapshot;
  response_snapshot: ResponseSnapshot | null;
  validation_results: ValidationResultOut[];
  duration_ms: number | null;
  error: string | null;
  created_at: IsoDateTime;
}

export interface ExecutionOut {
  id: Uuid;
  test_id: Uuid;
  test_name: string;
  environment_id: Uuid;
  environment_name: string;
  status: ExecutionStatus;
  started_at: IsoDateTime;
  finished_at: IsoDateTime | null;
  results: ExecutionResultOut[];
}

// ---------------------------------------------------------------------------
// Dependencies — edges between tests (a test depends on another test's
// extracted values), used to explain why a suite run skipped a test.
// ---------------------------------------------------------------------------

export interface DependencyOut {
  id: Uuid;
  test_id: Uuid;
  depends_on_test_id: Uuid;
  source: "auto" | "ai" | "user";
  reason: string | null;
  created_at: IsoDateTime;
}

// ---------------------------------------------------------------------------
// Chat assistant (PRD §17-18)
// ---------------------------------------------------------------------------

export interface ChatToolCallOut {
  tool: string;
  arguments: Record<string, unknown>;
  result: string;
  error: string | null;
}

export interface ChatOut {
  reply: string;
  tool_calls: ChatToolCallOut[];
  changes: ChatToolCallOut[];
}

export type ChatMessageRole = "user" | "assistant";

export interface ChatMessageOut {
  id: Uuid;
  role: ChatMessageRole;
  content: string;
  tool_calls: ChatToolCallOut[] | null;
  created_at: IsoDateTime;
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  /** Short machine-readable classification, e.g. "quota_exhausted" |
   *  "rate_limited" | "timeout" | "connection_error" | "unknown" — only
   *  present on endpoints that return a structured {message, reason}
   *  detail (generate-tests, chat). */
  readonly reason?: string;
  /** ISO-8601 quota/rate-limit reset time, only set when reason ===
   *  "quota_exhausted" AND the provider's own response actually supplied
   *  one — never fabricated, so this is frequently undefined even for a
   *  quota_exhausted error. */
  readonly resetAt?: string;
  /** Configured provider's short name (e.g. "nvidia_nim"), only present
   *  from generate-tests today — used to name the provider in the
   *  quota_exhausted message. */
  readonly provider?: string;

  constructor(
    status: number,
    detail: string,
    reason?: string,
    message?: string,
    resetAt?: string,
    provider?: string
  ) {
    super(message ?? `API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
    this.reason = reason;
    this.resetAt = resetAt;
    this.provider = provider;
  }
}

// ---------------------------------------------------------------------------
// Base request helper
// ---------------------------------------------------------------------------

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    let reason: string | undefined;
    let resetAt: string | undefined;
    let provider: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail && typeof body.detail === "object") {
        const d = body.detail as {
          message?: unknown;
          reason?: unknown;
          reset_at?: unknown;
          provider?: unknown;
        };
        detail =
          typeof d.message === "string" ? d.message : JSON.stringify(body.detail);
        reason = typeof d.reason === "string" ? d.reason : undefined;
        resetAt = typeof d.reset_at === "string" ? d.reset_at : undefined;
        provider = typeof d.provider === "string" ? d.provider : undefined;
      }
    } catch {
      // ignore JSON parse failure — keep statusText as detail
    }
    throw new ApiError(res.status, detail, reason, undefined, resetAt, provider);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Public API surface
// ---------------------------------------------------------------------------

export const api = {
  async listSuites(): Promise<SuiteSummaryOut[]> {
    return request<SuiteSummaryOut[]>("/api/suites");
  },

  async getSuite(id: Uuid): Promise<SuiteDetailOut> {
    return request<SuiteDetailOut>(`/api/suites/${id}`);
  },

  async importFromUpload(file: File): Promise<SuiteDetailOut> {
    const form = new FormData();
    form.append("file", file);
    // Do NOT set Content-Type — browser sets multipart boundary automatically
    const res = await fetch(`${baseUrl}/api/imports/upload`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { detail?: unknown };
        detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail);
      } catch {
        // ignore JSON parse failure
      }
      throw new ApiError(res.status, detail);
    }
    return res.json() as Promise<SuiteDetailOut>;
  },

  async importFromUrl(url: string): Promise<SuiteDetailOut> {
    return request<SuiteDetailOut>("/api/imports/url", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  },

  async generateTests(endpointId: Uuid): Promise<TestOut[]> {
    return request<TestOut[]>(`/api/endpoints/${endpointId}/generate-tests`, {
      method: "POST",
    });
  },

  async listTests(endpointId: Uuid): Promise<TestOut[]> {
    return request<TestOut[]>(`/api/endpoints/${endpointId}/tests`);
  },

  async getTest(testId: Uuid): Promise<TestOut> {
    return request<TestOut>(`/api/tests/${testId}`);
  },

  async importFromCurl(
    curlText: string,
    suiteName?: string
  ): Promise<SuiteDetailOut> {
    return request<SuiteDetailOut>("/api/imports/curl", {
      method: "POST",
      body: JSON.stringify({
        curl_text: curlText,
        suite_name: suiteName?.trim() ? suiteName.trim() : null,
      }),
    });
  },

  async listEnvironments(): Promise<EnvironmentOut[]> {
    return request<EnvironmentOut[]>("/api/environments");
  },

  async getEnvironment(id: Uuid): Promise<EnvironmentOut> {
    return request<EnvironmentOut>(`/api/environments/${id}`);
  },

  async createEnvironment(payload: EnvironmentIn): Promise<EnvironmentOut> {
    return request<EnvironmentOut>("/api/environments", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async updateEnvironment(
    id: Uuid,
    payload: EnvironmentUpdateIn
  ): Promise<EnvironmentOut> {
    return request<EnvironmentOut>(`/api/environments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  async deleteEnvironment(id: Uuid): Promise<void> {
    return request<void>(`/api/environments/${id}`, { method: "DELETE" });
  },

  async executeTest(testId: Uuid, environmentId: Uuid): Promise<ExecutionOut> {
    return request<ExecutionOut>(`/api/tests/${testId}/execute`, {
      method: "POST",
      body: JSON.stringify({ environment_id: environmentId }),
    });
  },

  async listExecutions(): Promise<ExecutionOut[]> {
    return request<ExecutionOut[]>("/api/executions");
  },

  async getExecution(id: Uuid): Promise<ExecutionOut> {
    return request<ExecutionOut>(`/api/executions/${id}`);
  },

  async executeSuite(suiteId: Uuid, environmentId: Uuid): Promise<ExecutionOut[]> {
    return request<ExecutionOut[]>(`/api/suites/${suiteId}/execute`, {
      method: "POST",
      body: JSON.stringify({ environment_id: environmentId }),
    });
  },

  async listDependencies(suiteId: Uuid): Promise<DependencyOut[]> {
    return request<DependencyOut[]>(`/api/suites/${suiteId}/dependencies`);
  },

  async detectDependencies(suiteId: Uuid): Promise<DependencyOut[]> {
    return request<DependencyOut[]>(`/api/suites/${suiteId}/detect-dependencies`, {
      method: "POST",
    });
  },

  async addDependency(
    suiteId: Uuid,
    testId: Uuid,
    dependsOnTestId: Uuid
  ): Promise<DependencyOut> {
    return request<DependencyOut>(`/api/suites/${suiteId}/dependencies`, {
      method: "POST",
      body: JSON.stringify({
        test_id: testId,
        depends_on_test_id: dependsOnTestId,
      }),
    });
  },

  async removeDependency(suiteId: Uuid, dependencyId: Uuid): Promise<void> {
    return request<void>(`/api/suites/${suiteId}/dependencies/${dependencyId}`, {
      method: "DELETE",
    });
  },

  async sendChatMessage(suiteId: Uuid, message: string): Promise<ChatOut> {
    return request<ChatOut>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ suite_id: suiteId, message }),
    });
  },

  async getChatHistory(suiteId: Uuid): Promise<ChatMessageOut[]> {
    return request<ChatMessageOut[]>(`/api/chat/${suiteId}/history`);
  },
};
