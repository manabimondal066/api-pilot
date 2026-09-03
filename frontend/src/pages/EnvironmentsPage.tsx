import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Globe, Plus, ServerCog, TriangleAlert } from "lucide-react";
import { api, ApiError, type EnvironmentOut } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ---------------------------------------------------------------------------
// Environment row
// ---------------------------------------------------------------------------

function EnvironmentRow({
  env,
  onDelete,
}: {
  env: EnvironmentOut;
  onDelete: (id: string) => void;
}) {
  const [deleting, setDeleting] = useState(false);

  function handleDelete() {
    if (!confirm(`Delete environment "${env.name}"? This cannot be undone.`)) {
      return;
    }
    setDeleting(true);
    onDelete(env.id);
  }

  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3.5">
      <div className="min-w-0 flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
          <Globe className="h-4.5 w-4.5" />
        </span>
        <div className="min-w-0">
          <p className="font-semibold text-foreground truncate flex items-center gap-1.5">
            {env.is_incomplete && (
              <span
                title="Incomplete — no auth configured. Edit this environment to fill in the missing piece."
                className="text-warning"
              >
                <TriangleAlert className="h-3.5 w-3.5" />
              </span>
            )}
            {env.name}
          </p>
          <p className="text-sm text-muted-foreground truncate mt-0.5">
            {env.base_url}
          </p>
        </div>
      </div>
      <div className="shrink-0 flex items-center gap-2">
        <Badge variant="neutral">{env.auth_type}</Badge>
        <Button asChild variant="outline" size="sm">
          <Link to={`/environments/${env.id}/edit`}>Edit</Link>
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={handleDelete}
          disabled={deleting}
        >
          {deleting ? "Deleting…" : "Delete"}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function EnvironmentsPage() {
  const [environments, setEnvironments] = useState<EnvironmentOut[] | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listEnvironments()
      .then((data) => {
        if (!cancelled) setEnvironments(data);
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Unknown error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  };

  useEffect(load, []);

  function handleDelete(id: string) {
    api
      .deleteEnvironment(id)
      .then(() => {
        setEnvironments((prev) => (prev ?? []).filter((e) => e.id !== id));
      })
      .catch((e: unknown) => {
        setError(
          e instanceof ApiError
            ? e.message
            : e instanceof Error
              ? e.message
              : "Failed to delete environment"
        );
      });
  }

  // --- Loading ---
  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-page-title">Environments</h1>
        <div className="space-y-2 animate-pulse">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-16 rounded-xl bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  // --- Error ---
  if (error && environments === null) {
    return (
      <div className="space-y-3">
        <h1 className="text-page-title">Environments</h1>
        <div className="rounded-xl border border-danger-border bg-danger-bg p-4">
          <p className="text-danger font-semibold">
            Failed to load environments
          </p>
          <p className="text-sm text-muted-foreground mt-1">{error}</p>
        </div>
        <Button variant="outline" onClick={load}>
          Retry
        </Button>
      </div>
    );
  }

  // --- Empty ---
  if (environments !== null && environments.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-page-title">Environments</h1>
        <div className="text-center py-20 border-2 border-dashed border-border rounded-2xl bg-card/40">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-accent text-accent-foreground mb-4">
            <ServerCog className="h-6 w-6" />
          </div>
          <p className="text-foreground text-lg font-semibold">No environments yet</p>
          <p className="text-muted-foreground text-sm mt-1">
            Add an environment to run tests against a real API.
          </p>
          <Button asChild variant="brand" className="mt-6">
            <Link to="/environments/new">
              <Plus className="h-4 w-4" /> New Environment
            </Link>
          </Button>
        </div>
      </div>
    );
  }

  // --- Success ---
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-page-title">Environments</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {environments?.length ?? 0} environment{environments?.length !== 1 ? "s" : ""}
          </p>
        </div>
        <Button asChild variant="brand" size="sm">
          <Link to="/environments/new">
            <Plus className="h-4 w-4" /> New Environment
          </Link>
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-danger-border bg-danger-bg p-3">
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      <Card className="divide-y divide-border overflow-hidden">
        {(environments ?? []).map((env) => (
          <EnvironmentRow key={env.id} env={env} onDelete={handleDelete} />
        ))}
      </Card>
    </div>
  );
}
