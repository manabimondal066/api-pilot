import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, TriangleAlert, X } from "lucide-react";
import {
  api,
  ApiError,
  type EnvironmentAuthType,
  type EnvironmentOut,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { inputClass } from "@/lib/utils";

const labelCls = "text-sm font-medium text-foreground";

const AUTH_TYPES: { value: EnvironmentAuthType; label: string }[] = [
  { value: "none", label: "None" },
  { value: "bearer", label: "Bearer token" },
  { value: "basic", label: "Basic auth" },
  { value: "api_key", label: "API key" },
];

interface HeaderRow {
  key: string;
  value: string;
}

function headersToRows(headers: Record<string, string>): HeaderRow[] {
  const rows = Object.entries(headers).map(([key, value]) => ({ key, value }));
  return rows.length > 0 ? rows : [{ key: "", value: "" }];
}

function rowsToHeaders(rows: HeaderRow[]): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (key) headers[key] = row.value;
  }
  return headers;
}

// ---------------------------------------------------------------------------
// Auth credential fields — shape depends on the selected auth type
// ---------------------------------------------------------------------------

function AuthFields({
  authType,
  authConfig,
  onChange,
}: {
  authType: EnvironmentAuthType;
  authConfig: Record<string, string>;
  onChange: (config: Record<string, string>) => void;
}) {
  if (authType === "none") return null;

  if (authType === "bearer") {
    return (
      <div className="space-y-1.5">
        <label className={labelCls}>Token</label>
        <input
          type="password"
          value={authConfig.token ?? ""}
          onChange={(e) => onChange({ ...authConfig, token: e.target.value })}
          placeholder="Bearer token"
          className={inputClass}
        />
      </div>
    );
  }

  if (authType === "basic") {
    return (
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className={labelCls}>Username</label>
          <input
            type="text"
            value={authConfig.username ?? ""}
            onChange={(e) =>
              onChange({ ...authConfig, username: e.target.value })
            }
            className={inputClass}
          />
        </div>
        <div className="space-y-1.5">
          <label className={labelCls}>Password</label>
          <input
            type="password"
            value={authConfig.password ?? ""}
            onChange={(e) =>
              onChange({ ...authConfig, password: e.target.value })
            }
            className={inputClass}
          />
        </div>
      </div>
    );
  }

  // api_key
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="space-y-1.5">
        <label className={labelCls}>Header name</label>
        <input
          type="text"
          value={authConfig.header ?? "X-API-Key"}
          onChange={(e) => onChange({ ...authConfig, header: e.target.value })}
          className={inputClass}
        />
      </div>
      <div className="space-y-1.5">
        <label className={labelCls}>Value</label>
        <input
          type="password"
          value={authConfig.value ?? ""}
          onChange={(e) => onChange({ ...authConfig, value: e.target.value })}
          className={inputClass}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Default headers editor — add/remove key-value rows
// ---------------------------------------------------------------------------

function HeaderRows({
  rows,
  onChange,
}: {
  rows: HeaderRow[];
  onChange: (rows: HeaderRow[]) => void;
}) {
  function update(index: number, field: "key" | "value", value: string) {
    onChange(
      rows.map((row, i) => (i === index ? { ...row, [field]: value } : row))
    );
  }

  function remove(index: number) {
    const next = rows.filter((_, i) => i !== index);
    onChange(next.length > 0 ? next : [{ key: "", value: "" }]);
  }

  function add() {
    onChange([...rows, { key: "", value: "" }]);
  }

  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Header name"
            value={row.key}
            onChange={(e) => update(i, "key", e.target.value)}
            className={inputClass}
          />
          <input
            type="text"
            placeholder="Value"
            value={row.value}
            onChange={(e) => update(i, "value", e.target.value)}
            className={inputClass}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => remove(i)}
            aria-label="Remove header"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        + Add header
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Auth header name — mirrors backend `_apply_auth` in execution_engine.py,
// so we can warn about a Default header that collides (case-insensitively)
// with the header the Auth type config will actually send.
// ---------------------------------------------------------------------------

function authHeaderName(
  authType: EnvironmentAuthType,
  authConfig: Record<string, string>
): string | null {
  if (authType === "bearer" || authType === "basic") return "Authorization";
  if (authType === "api_key") return authConfig.header?.trim() || "X-API-Key";
  return null;
}

// ---------------------------------------------------------------------------
// Page — handles both create (no :id) and edit (:id present)
// ---------------------------------------------------------------------------

export function EnvironmentFormPage() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();

  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [authType, setAuthType] = useState<EnvironmentAuthType>("none");
  const [authConfig, setAuthConfig] = useState<Record<string, string>>({});
  const [headerRows, setHeaderRows] = useState<HeaderRow[]>([
    { key: "", value: "" },
  ]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    api
      .getEnvironment(id)
      .then((env: EnvironmentOut) => {
        if (cancelled) return;
        setName(env.name);
        setBaseUrl(env.base_url);
        setAuthType((env.auth_type as EnvironmentAuthType) ?? "none");
        setAuthConfig(
          Object.fromEntries(
            Object.entries(env.auth_config).map(([k, v]) => [k, String(v)])
          )
        );
        setHeaderRows(headersToRows(env.default_headers));
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setLoadError(e instanceof Error ? e.message : "Unknown error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !baseUrl.trim()) return;

    setSaving(true);
    setSaveError(null);

    const payload = {
      name: name.trim(),
      base_url: baseUrl.trim(),
      auth_type: authType,
      auth_config: authType === "none" ? {} : authConfig,
      default_headers: rowsToHeaders(headerRows),
    };

    const request = isEdit
      ? api.updateEnvironment(id!, payload)
      : api.createEnvironment(payload);

    request
      .then(() => navigate("/environments"))
      .catch((e: unknown) => {
        setSaveError(
          e instanceof ApiError
            ? e.message
            : e instanceof Error
              ? e.message
              : "Save failed"
        );
      })
      .finally(() => setSaving(false));
  }

  if (loading) {
    return (
      <div className="space-y-3 max-w-xl">
        <h1 className="text-page-title">Loading…</h1>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="space-y-4 max-w-xl">
        <Link
          to="/environments"
          className="text-primary hover:underline text-sm inline-flex items-center gap-1"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to environments
        </Link>
        <div className="rounded-xl border border-danger-border bg-danger-bg p-4">
          <p className="text-danger font-semibold">
            Failed to load environment
          </p>
          <p className="text-sm text-muted-foreground mt-1">{loadError}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-xl space-y-6 animate-fade-in">
      <div>
        <Link
          to="/environments"
          className="text-primary hover:underline text-sm inline-flex items-center gap-1"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to environments
        </Link>
        <h1 className="text-page-title mt-3">
          {isEdit ? "Edit Environment" : "New Environment"}
        </h1>
      </div>

      <Card className="p-6">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <label className={labelCls}>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="QA"
              required
              disabled={saving}
              className={inputClass}
            />
          </div>

          <div className="space-y-1.5">
            <label className={labelCls}>Base URL</label>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://qa-api.example.com"
              required
              disabled={saving}
              className={inputClass}
            />
          </div>

          <div className="space-y-1.5">
            <label className={labelCls}>Auth type</label>
            <select
              value={authType}
              onChange={(e) => {
                setAuthType(e.target.value as EnvironmentAuthType);
                setAuthConfig({});
              }}
              disabled={saving}
              className={inputClass}
            >
              {AUTH_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <AuthFields
            authType={authType}
            authConfig={authConfig}
            onChange={setAuthConfig}
          />

          <div className="space-y-1.5">
            <label className={labelCls}>Default headers</label>
            <HeaderRows rows={headerRows} onChange={setHeaderRows} />
            {(() => {
              const authHeader = authHeaderName(authType, authConfig);
              if (!authHeader) return null;
              const colliding = headerRows.filter(
                (row) =>
                  row.key.trim().toLowerCase() === authHeader.toLowerCase()
              );
              if (colliding.length === 0) return null;
              return (
                <p className="text-sm text-warning flex items-start gap-1.5">
                  <TriangleAlert className="h-4 w-4 shrink-0 mt-0.5" />
                  "{colliding[0].key}" here has the same name as the Auth
                  type header ("{authHeader}") — the Auth type value will be
                  used and this row will be ignored at request time. Remove
                  this row or rename it to avoid confusion.
                </p>
              );
            })()}
          </div>

          {saveError && <p className="text-sm text-destructive">{saveError}</p>}

          <div className="flex items-center gap-2 pt-1">
            <Button
              type="submit"
              variant="brand"
              disabled={saving || !name.trim() || !baseUrl.trim()}
            >
              {saving ? "Saving…" : isEdit ? "Save changes" : "Create environment"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate("/environments")}
              disabled={saving}
            >
              Cancel
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
