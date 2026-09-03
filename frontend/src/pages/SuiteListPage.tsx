import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CircleCheck, CircleX, FolderOpen, Loader2, Plus } from "lucide-react";
import { api, type SuiteSummaryOut } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, type BadgeProps } from "@/components/ui/badge";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_VARIANT: Record<string, BadgeProps["variant"]> = {
  parsed: "success",
  pending: "warning",
  failed: "danger",
};

const STATUS_ICON: Record<string, ReactNode> = {
  parsed: <CircleCheck />,
  pending: <Loader2 className="animate-spin" />,
  failed: <CircleX />,
};

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={STATUS_VARIANT[status] ?? "neutral"} icon={STATUS_ICON[status]}>
      {status}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Suite card
// ---------------------------------------------------------------------------

function SuiteCard({ suite }: { suite: SuiteSummaryOut }) {
  return (
    <Link to={`/suites/${suite.id}`} className="group block">
      <Card className="p-4 hover:shadow-[var(--shadow-card-hover)] hover:-translate-y-0.5 hover:border-primary/30 transition-all duration-200">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <FolderOpen className="h-4.5 w-4.5" />
            </span>
            <div className="min-w-0">
              <p className="font-semibold text-foreground truncate group-hover:text-primary transition-colors">
                {suite.name}
              </p>
              <p className="text-sm text-muted-foreground mt-0.5">
                {suite.endpoint_count} endpoint
                {suite.endpoint_count !== 1 ? "s" : ""}
              </p>
            </div>
          </div>
          <div className="shrink-0 flex flex-col items-end gap-1.5">
            <StatusBadge status={suite.generation_status} />
            <span className="text-xs text-muted-foreground">
              {new Date(suite.created_at).toLocaleString()}
            </span>
          </div>
        </div>
      </Card>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function SuiteListPage() {
  const [suites, setSuites] = useState<SuiteSummaryOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listSuites()
      .then((data) => {
        if (!cancelled) setSuites(data);
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

  // --- Loading ---
  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-page-title">Suites</h1>
        <div className="space-y-3 animate-pulse">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-[4.5rem] rounded-xl bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  // --- Error ---
  if (error) {
    return (
      <div className="space-y-3">
        <h1 className="text-page-title">Suites</h1>
        <div className="rounded-xl border border-danger-border bg-danger-bg p-4">
          <p className="text-danger font-semibold">Failed to load suites</p>
          <p className="text-sm text-muted-foreground mt-1">{error}</p>
        </div>
        <Button variant="outline" onClick={load}>
          Retry
        </Button>
      </div>
    );
  }

  // --- Empty ---
  if (suites !== null && suites.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-page-title">Suites</h1>
        <div className="text-center py-20 border-2 border-dashed border-border rounded-2xl bg-card/40">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-accent text-accent-foreground mb-4">
            <FolderOpen className="h-6 w-6" />
          </div>
          <p className="text-foreground text-lg font-semibold">No suites yet</p>
          <p className="text-muted-foreground text-sm mt-1">
            Import a Swagger / OpenAPI spec to get started.
          </p>
          <Button asChild variant="brand" className="mt-6">
            <Link to="/import">
              Import your first spec <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
        </div>
      </div>
    );
  }

  // --- Success ---
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-page-title">Suites</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {suites?.length ?? 0} test suite{suites?.length !== 1 ? "s" : ""}
          </p>
        </div>
        <Button asChild variant="brand" size="sm">
          <Link to="/import">
            <Plus className="h-4 w-4" /> Import
          </Link>
        </Button>
      </div>
      <div className="space-y-3 stagger-in">
        {(suites ?? []).map((s) => (
          <SuiteCard key={s.id} suite={s} />
        ))}
      </div>
    </div>
  );
}
