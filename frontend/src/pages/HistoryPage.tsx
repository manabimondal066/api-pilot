import { useEffect, useState } from "react";
import { ChevronRight, CircleAlert, CircleCheck, CircleX, History, MinusCircle } from "lucide-react";
import { api, ApiError, type ExecutionOut, type TestOut } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TestDetailPanel, type RunState } from "@/components/EndpointTests";

// ---------------------------------------------------------------------------
// Status badge — mirrors the pass/fail/error styling used on test cards
// (app/components/EndpointTests.tsx ResultBadge) so history reads the same
// way the live run view does.
// ---------------------------------------------------------------------------

function resultStatus(execution: ExecutionOut): "passed" | "failed" | "error" | "skipped" {
  return execution.results[0]?.status ?? "error";
}

function StatusBadge({ execution }: { execution: ExecutionOut }) {
  const status = resultStatus(execution);
  if (status === "passed") {
    return (
      <Badge variant="success" icon={<CircleCheck />}>
        Passed
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="danger" icon={<CircleX />}>
        Failed
      </Badge>
    );
  }
  if (status === "skipped") {
    return (
      <Badge variant="neutral" icon={<MinusCircle />}>
        Skipped
      </Badge>
    );
  }
  return (
    <Badge variant="warning" icon={<CircleAlert />}>
      Error
    </Badge>
  );
}

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

// ---------------------------------------------------------------------------
// One history row
// ---------------------------------------------------------------------------

function ExecutionRow({
  execution,
  onClick,
}: {
  execution: ExecutionOut;
  onClick: () => void;
}) {
  const result = execution.results[0];
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-4 px-4 py-3.5 hover:bg-accent/40 transition-colors duration-150"
    >
      <div className="min-w-0">
        <p className="text-sm font-medium truncate">{execution.test_name}</p>
        <p className="text-xs text-muted-foreground truncate mt-0.5">
          {execution.environment_name}
        </p>
      </div>
      <StatusBadge execution={execution} />
      <span className="text-xs text-muted-foreground font-mono whitespace-nowrap">
        {formatDuration(result?.duration_ms)}
      </span>
      <span className="text-xs text-muted-foreground whitespace-nowrap">
        {new Date(execution.started_at).toLocaleString()}
      </span>
      <ChevronRight className="h-4 w-4 text-muted-foreground" />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function HistoryPage() {
  const [executions, setExecutions] = useState<ExecutionOut[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<{
    execution: ExecutionOut;
    test: TestOut;
  } | null>(null);
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const load = () => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listExecutions()
      .then((data) => {
        if (!cancelled) setExecutions(data);
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

  function openDetail(execution: ExecutionOut) {
    setDetailError(null);
    setDetailLoadingId(execution.id);
    api
      .getTest(execution.test_id)
      .then((test) => {
        setSelected({ execution, test });
      })
      .catch((e: unknown) => {
        setDetailError(
          e instanceof ApiError
            ? `Couldn't load this test's details: ${e.detail}`
            : "Couldn't load this test's details. It may have been deleted."
        );
      })
      .finally(() => setDetailLoadingId(null));
  }

  // --- Loading ---
  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-page-title">History</h1>
        <div className="space-y-2 animate-pulse">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="h-14 rounded-xl bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  // --- Error ---
  if (error) {
    return (
      <div className="space-y-3">
        <h1 className="text-page-title">History</h1>
        <div className="rounded-xl border border-danger-border bg-danger-bg p-4">
          <p className="text-danger font-semibold">
            Failed to load execution history
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
  if (executions !== null && executions.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-page-title">History</h1>
        <div className="text-center py-20 border-2 border-dashed border-border rounded-2xl bg-card/40">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-accent text-accent-foreground mb-4">
            <History className="h-6 w-6" />
          </div>
          <p className="text-foreground text-lg font-semibold">No executions yet</p>
          <p className="text-muted-foreground text-sm mt-1">
            Run a test from a suite to see its result here.
          </p>
        </div>
      </div>
    );
  }

  // --- Success ---
  return (
    <div className="space-y-4 animate-fade-in">
      <div>
        <h1 className="text-page-title">History</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {executions?.length ?? 0} execution{executions?.length !== 1 ? "s" : ""}
        </p>
      </div>

      {detailError && (
        <div className="rounded-lg border border-danger-border bg-danger-bg p-3">
          <p className="text-sm text-danger">{detailError}</p>
        </div>
      )}

      <Card className="divide-y divide-border overflow-hidden">
        <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 px-4 py-2.5 text-eyebrow bg-muted/40">
          <span>Test / Environment</span>
          <span>Status</span>
          <span>Duration</span>
          <span>Run at</span>
          <span />
        </div>
        {(executions ?? []).map((exec) => (
          <ExecutionRow
            key={exec.id}
            execution={exec}
            onClick={() => openDetail(exec)}
          />
        ))}
      </Card>

      {detailLoadingId && (
        <p className="text-sm text-muted-foreground">Loading details…</p>
      )}

      {selected && (
        <TestDetailPanel
          test={selected.test}
          runState={buildRunState(selected.execution)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

function buildRunState(execution: ExecutionOut): RunState {
  const result = execution.results[0];
  if (!result) {
    return {
      kind: "error",
      message: "This execution has no recorded result.",
    };
  }
  return { kind: "done", execution, result };
}
