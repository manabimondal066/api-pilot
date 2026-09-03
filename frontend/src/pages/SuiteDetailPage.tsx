import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  CircleCheck,
  CircleHelp,
  CircleX,
  Loader2,
  Network,
  Play,
  Plus,
} from "lucide-react";
import {
  api,
  ApiError,
  type DependencyOut,
  type EnvironmentOut,
  type ExecutionOut,
  type SuiteDetailOut,
  type TestOut,
  type Uuid,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { inputClass } from "@/lib/utils";
import { HttpMethodPill } from "@/components/HttpMethodPill";
import { EndpointTests } from "@/components/EndpointTests";
import { ChatPanel } from "@/components/ChatPanel";

// ---------------------------------------------------------------------------
// Status badge (inline — no extra shared component needed yet)
// ---------------------------------------------------------------------------

const STATUS_VARIANT: Record<string, BadgeProps["variant"]> = {
  parsed: "success",
  pending: "warning",
  failed: "danger",
};

function StatusBadge({ status }: { status: string }) {
  return <Badge variant={STATUS_VARIANT[status] ?? "neutral"}>{status}</Badge>;
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-4 bg-muted rounded w-24" />
      <div className="h-8 bg-muted rounded w-1/2 mt-3" />
      <div className="h-4 bg-muted rounded w-1/3" />
      <div className="space-y-2 mt-6">
        {Array.from({ length: 7 }, (_, i) => (
          <div key={i} className="h-14 bg-muted rounded-xl" />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Environment selector — lets the user pick which real API the "Run"
// buttons on each test card will execute against. State lives in the page
// component so the selection is remembered while navigating around the
// page (it resets on a fresh page load, which is expected).
// ---------------------------------------------------------------------------

function EnvironmentSelector({
  environments,
  selectedId,
  onChange,
}: {
  environments: EnvironmentOut[];
  selectedId: Uuid | null;
  onChange: (id: Uuid | null) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor="environment-select"
        className="text-sm font-medium text-muted-foreground"
      >
        Environment
      </label>
      <select
        id="environment-select"
        value={selectedId ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className={`${inputClass} w-auto py-1.5`}
      >
        <option value="">Select environment…</option>
        {environments.map((env) => (
          <option key={env.id} value={env.id}>
            {env.is_incomplete ? `⚠ ${env.name} (incomplete)` : env.name}
          </option>
        ))}
      </select>
      {environments.some((env) => env.id === selectedId && env.is_incomplete) && (
        <Link
          to="/environments"
          className="text-xs text-warning hover:underline"
          title="This environment has no auth configured — fill in the missing piece."
        >
          ⚠ Incomplete — edit
        </Link>
      )}
      {environments.length === 0 && (
        <Link
          to="/environments"
          className="text-xs text-primary hover:underline"
        >
          + Add an environment
        </Link>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Run Suite — executes every test in the suite, dependency order handled
// entirely server-side (POST /api/suites/{id}/execute). A suite run can
// legitimately take a while (one real HTTP call per test, sequentially),
// so the loading state says so explicitly rather than showing a bare
// spinner that starts looking frozen after a few seconds.
// ---------------------------------------------------------------------------

type SuiteRunState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "error"; message: string }
  | { kind: "done"; resultsByTestId: Record<Uuid, ExecutionOut> };

function messageFromSuiteRunError(e: unknown): string {
  // The backend already writes a clear, specific message for the failure-
  // to-start cases this is meant to surface — a dependency cycle names the
  // exact tests involved (app/services/suite_execution_service.py), and a
  // missing suite/environment says so plainly. Fall back only for the
  // truly unexpected case (network error, unparseable response, etc.).
  if (e instanceof ApiError) return e.detail || e.message;
  return "Couldn't run the suite. Try again.";
}

// Tallies each test's result status into the buckets the summary reports.
// 'error' (the request itself couldn't complete — timeout, connection
// failure, etc.) is folded into "failed" for this headline count; each
// test's own card/badge still shows Error distinctly. 'inconclusive' (Fix B
// — every enforced validation passed, only advisory ones didn't) gets its
// own bucket rather than being folded into "failed" — an advisory failure
// must never read as a failure in the aggregate either.
function summarizeSuiteRun(resultsByTestId: Record<Uuid, ExecutionOut>): {
  passed: number;
  inconclusive: number;
  failed: number;
  skipped: number;
  total: number;
} {
  let passed = 0;
  let inconclusive = 0;
  let failed = 0;
  let skipped = 0;
  for (const execution of Object.values(resultsByTestId)) {
    const status = execution.results[0]?.status;
    if (status === "passed") passed += 1;
    else if (status === "inconclusive") inconclusive += 1;
    else if (status === "skipped") skipped += 1;
    else failed += 1; // "failed" | "error" | missing result
  }
  return {
    passed,
    inconclusive,
    failed,
    skipped,
    total: Object.keys(resultsByTestId).length,
  };
}

function SuiteRunSummary({
  resultsByTestId,
}: {
  resultsByTestId: Record<Uuid, ExecutionOut>;
}) {
  const { passed, inconclusive, failed, skipped, total } = summarizeSuiteRun(resultsByTestId);

  if (total === 0) {
    return (
      <div className="rounded-lg border border-warning-border bg-warning-bg px-3 py-2.5">
        <p className="text-sm text-warning">
          This suite has no tests to run. Generate tests for at least one
          endpoint, then run the suite again.
        </p>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 text-sm animate-fade-in">
      <span className="inline-flex items-center gap-1 font-semibold text-success">
        <CircleCheck className="h-4 w-4" /> {passed}
      </span>
      {inconclusive > 0 && (
        <span className="inline-flex items-center gap-1 font-semibold text-info">
          <CircleHelp className="h-4 w-4" /> {inconclusive}
        </span>
      )}
      <span className="inline-flex items-center gap-1 font-semibold text-danger">
        <CircleX className="h-4 w-4" /> {failed}
      </span>
      <span className="inline-flex items-center gap-1 font-semibold text-muted-foreground">
        {skipped} skipped
      </span>
      <span className="text-muted-foreground">— see each test's badge below for details.</span>
    </div>
  );
}

function RunSuiteControls({
  environmentId,
  runState,
  onRun,
}: {
  environmentId: Uuid | null;
  runState: SuiteRunState;
  onRun: () => void;
}) {
  const running = runState.kind === "running";
  const runDisabled = !environmentId || running;

  return (
    <div className="space-y-2">
      <span
        title={!environmentId ? "Select an environment above to run this suite" : undefined}
      >
        <Button size="sm" variant="brand" onClick={onRun} disabled={runDisabled}>
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {running ? "Running…" : "Run Suite"}
        </Button>
      </span>

      {running && (
        <div className="flex items-center gap-3 rounded-lg border border-primary/20 bg-accent/50 px-3 py-2.5 text-sm animate-fade-in">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden="true" />
          <div>
            <div className="text-foreground font-medium">
              Running suite… this may take a few minutes
            </div>
            <div className="text-xs text-muted-foreground">
              Each test runs one at a time, in dependency order.
            </div>
          </div>
        </div>
      )}

      {runState.kind === "error" && (
        <div className="rounded-lg border border-danger-border bg-danger-bg px-3 py-2.5">
          <p className="text-sm text-danger">{runState.message}</p>
          <Button size="sm" variant="outline" className="mt-2" onClick={onRun}>
            Try Again
          </Button>
        </div>
      )}

      {runState.kind === "done" && (
        <SuiteRunSummary resultsByTestId={runState.resultsByTestId} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dependencies panel (PRD §12 / §2.3) — "Detect Dependencies" re-runs the
// heuristic detector; below it, a simple manual-override form lets the user
// add or remove an edge directly. No graph visualization in V1 — a flat
// list is enough to see and adjust what depends on what.
// ---------------------------------------------------------------------------

type DetectState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "error"; message: string }
  | { kind: "done"; count: number };

function messageFromDependencyError(e: unknown): string {
  if (e instanceof ApiError) return e.detail || e.message;
  return "Something went wrong. Try again.";
}

function DependenciesPanel({
  testNamesById,
  dependencyEdges,
  detectState,
  onDetect,
  onAdd,
  onRemove,
  addError,
}: {
  testNamesById: Record<Uuid, string>;
  dependencyEdges: DependencyOut[];
  detectState: DetectState;
  onDetect: () => void;
  onAdd: (testId: Uuid, dependsOnTestId: Uuid) => void;
  onRemove: (dependencyId: Uuid) => void;
  addError: string | null;
}) {
  const testOptions = Object.entries(testNamesById).sort((a, b) =>
    a[1].localeCompare(b[1])
  );
  const [testId, setTestId] = useState("");
  const [dependsOnTestId, setDependsOnTestId] = useState("");

  const detecting = detectState.kind === "running";
  const canAdd = testId && dependsOnTestId && testId !== dependsOnTestId;

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            <Network className="h-4.5 w-4.5" />
          </span>
          <div>
            <h2 className="text-section-title">Dependencies</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Which tests depend on which — detected automatically or added by
              hand.
            </p>
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={onDetect} disabled={detecting}>
          {detecting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {detecting ? "Detecting…" : "Detect Dependencies"}
        </Button>
      </div>

      {detectState.kind === "error" && (
        <p className="text-sm text-danger">{detectState.message}</p>
      )}
      {detectState.kind === "done" && (
        <p className="text-sm text-muted-foreground">
          Detection complete — {detectState.count} dependenc
          {detectState.count === 1 ? "y" : "ies"} found.
        </p>
      )}

      {/* --- Current edges --------------------------------------------- */}
      {dependencyEdges.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No dependencies yet. Click "Detect Dependencies", or add one
          manually below.
        </p>
      ) : (
        <ul className="space-y-1.5 stagger-in">
          {dependencyEdges.map((edge) => (
            <li
              key={edge.id}
              className="flex items-center justify-between gap-3 text-sm rounded-lg border border-border bg-card/60 px-3 py-2"
            >
              <span className="min-w-0 truncate">
                <span className="font-medium">
                  {testNamesById[edge.test_id] ?? "(unknown test)"}
                </span>
                <span className="text-muted-foreground"> depends on </span>
                <span className="font-medium">
                  {testNamesById[edge.depends_on_test_id] ?? "(unknown test)"}
                </span>
                <span className="text-xs font-mono text-muted-foreground ml-2">
                  ({edge.source})
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="shrink-0 text-destructive hover:text-destructive hover:bg-danger-bg"
                onClick={() => onRemove(edge.id)}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}

      {/* --- Manual add form --------------------------------------------- */}
      <div className="pt-3 border-t border-border/70 space-y-2">
        <div className="text-eyebrow">
          Add a dependency
        </div>
        {testOptions.length < 2 ? (
          <p className="text-sm text-muted-foreground">
            Generate at least two tests to add a manual dependency.
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={testId}
              onChange={(e) => setTestId(e.target.value)}
              className={`${inputClass} w-auto max-w-[220px] py-1.5`}
            >
              <option value="">Select test…</option>
              {testOptions.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
            <span className="text-sm text-muted-foreground">depends on</span>
            <select
              value={dependsOnTestId}
              onChange={(e) => setDependsOnTestId(e.target.value)}
              className={`${inputClass} w-auto max-w-[220px] py-1.5`}
            >
              <option value="">Select test…</option>
              {testOptions.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              disabled={!canAdd}
              onClick={() => {
                onAdd(testId, dependsOnTestId);
                setTestId("");
                setDependsOnTestId("");
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Add
            </Button>
          </div>
        )}
        {addError && <p className="text-sm text-danger">{addError}</p>}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function SuiteDetailPage() {
  const { id } = useParams();

  const [loading, setLoading] = useState(true);
  const [suite, setSuite] = useState<SuiteDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isNotFound, setIsNotFound] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  const [environments, setEnvironments] = useState<EnvironmentOut[]>([]);
  const [selectedEnvironmentId, setSelectedEnvironmentId] =
    useState<Uuid | null>(null);

  const [dependencyEdges, setDependencyEdges] = useState<DependencyOut[]>([]);
  const [testNamesById, setTestNamesById] = useState<Record<Uuid, string>>({});
  const [suiteRunState, setSuiteRunState] = useState<SuiteRunState>({ kind: "idle" });
  const [detectState, setDetectState] = useState<DetectState>({ kind: "idle" });
  const [addDependencyError, setAddDependencyError] = useState<string | null>(null);
  // Bumped whenever the chat assistant reports a change (e.g. it added a
  // validation or fixed a test body) — passed to every EndpointTests
  // instance to force a quiet refetch, so the updated test shows up
  // without a manual page reload.
  const [testsRefreshToken, setTestsRefreshToken] = useState(0);

  // Aggregates each EndpointTests instance's own test list into one
  // suite-wide id -> name map, so a skip reason can name a dependency test
  // that belongs to a different endpoint than the one being viewed.
  const handleTestsLoaded = useCallback((_endpointId: Uuid, tests: TestOut[]) => {
    setTestNamesById((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const t of tests) {
        if (next[t.id] !== t.name) {
          next[t.id] = t.name;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listEnvironments()
      .then((data) => {
        if (!cancelled) setEnvironments(data);
      })
      .catch(() => {
        // Silent — the selector just shows empty; the rest of the page
        // (endpoints, tests) still works without an environment picked.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!id) {
      setIsNotFound(true);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setSuite(null);
    setError(null);
    setIsNotFound(false);

    api
      .getSuite(id)
      .then((data) => {
        if (!cancelled) {
          setSuite(data);
          setLoading(false);
          setSelectedEnvironmentId((prev) => prev ?? data.environment_id);
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setIsNotFound(true);
        } else {
          setError(e instanceof Error ? e.message : "Unknown error");
        }
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id, retryCount]);

  useEffect(() => {
    if (!suite) return;
    let cancelled = false;
    api
      .listDependencies(suite.id)
      .then((data) => {
        if (!cancelled) setDependencyEdges(data);
      })
      .catch(() => {
        // Silent — worst case, a skip reason falls back to a generic
        // message instead of naming the specific failed dependency.
      });
    return () => {
      cancelled = true;
    };
  }, [suite]);

  function runSuite() {
    if (!suite || !selectedEnvironmentId) return;
    setSuiteRunState({ kind: "running" });
    api
      .executeSuite(suite.id, selectedEnvironmentId)
      .then((executions) => {
        const resultsByTestId: Record<Uuid, ExecutionOut> = {};
        for (const execution of executions) {
          resultsByTestId[execution.test_id] = execution;
        }
        setSuiteRunState({ kind: "done", resultsByTestId });
      })
      .catch((e: unknown) => {
        setSuiteRunState({ kind: "error", message: messageFromSuiteRunError(e) });
      });
  }

  function runDetectDependencies() {
    if (!suite) return;
    setDetectState({ kind: "running" });
    api
      .detectDependencies(suite.id)
      .then((edges) => {
        setDependencyEdges(edges);
        setDetectState({ kind: "done", count: edges.length });
      })
      .catch((e: unknown) => {
        setDetectState({ kind: "error", message: messageFromDependencyError(e) });
      });
  }

  function addDependency(testId: Uuid, dependsOnTestId: Uuid) {
    if (!suite) return;
    setAddDependencyError(null);
    api
      .addDependency(suite.id, testId, dependsOnTestId)
      .then((edge) => {
        setDependencyEdges((prev) => [edge, ...prev]);
      })
      .catch((e: unknown) => {
        setAddDependencyError(messageFromDependencyError(e));
      });
  }

  function removeDependency(dependencyId: Uuid) {
    if (!suite) return;
    api
      .removeDependency(suite.id, dependencyId)
      .then(() => {
        setDependencyEdges((prev) => prev.filter((d) => d.id !== dependencyId));
      })
      .catch(() => {
        // Best-effort — the list simply won't update; the user can retry.
      });
  }

  // --- Loading ---
  if (loading) return <LoadingSkeleton />;

  // --- Not found ---
  if (isNotFound) {
    return (
      <div className="space-y-4">
        <Link to="/" className="text-primary hover:underline text-sm inline-flex items-center gap-1">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to suites
        </Link>
        <h1 className="text-page-title mt-4">Suite not found</h1>
        <p className="text-muted-foreground text-sm">
          This suite doesn't exist or has been deleted.
        </p>
      </div>
    );
  }

  // --- Error ---
  if (error) {
    return (
      <div className="space-y-4">
        <Link to="/" className="text-primary hover:underline text-sm inline-flex items-center gap-1">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to suites
        </Link>
        <div className="rounded-xl border border-danger-border bg-danger-bg p-4">
          <p className="text-danger font-semibold">Failed to load suite</p>
          <p className="text-sm text-muted-foreground mt-1">{error}</p>
        </div>
        <Button variant="outline" onClick={() => setRetryCount((c) => c + 1)}>
          Retry
        </Button>
      </div>
    );
  }

  // Guard: should be unreachable if states are set correctly
  if (!suite) return null;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* ---- Header -------------------------------------------------------- */}
      <div>
        <Link to="/" className="text-primary hover:underline text-sm inline-flex items-center gap-1">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to suites
        </Link>

        <div className="flex items-start justify-between gap-4 mt-3">
          <h1 className="text-page-title">{suite.name}</h1>
          <span className="mt-1 shrink-0">
            <StatusBadge status={suite.generation_status} />
          </span>
        </div>

        <p className="text-sm text-muted-foreground mt-1">
          {suite.endpoints.length} endpoint
          {suite.endpoints.length !== 1 ? "s" : ""} · Created{" "}
          {new Date(suite.created_at).toLocaleString()}
        </p>

        <div className="mt-4 flex flex-wrap items-start gap-4">
          <EnvironmentSelector
            environments={environments}
            selectedId={selectedEnvironmentId}
            onChange={setSelectedEnvironmentId}
          />
          <RunSuiteControls
            environmentId={selectedEnvironmentId}
            runState={suiteRunState}
            onRun={runSuite}
          />
        </div>
      </div>

      {/* ---- Dependencies ---------------------------------------------------- */}
      <DependenciesPanel
        testNamesById={testNamesById}
        dependencyEdges={dependencyEdges}
        detectState={detectState}
        onDetect={runDetectDependencies}
        onAdd={addDependency}
        onRemove={removeDependency}
        addError={addDependencyError}
      />

      {/* ---- Endpoint list ------------------------------------------------- */}
      <div>
        <h2 className="text-section-title mb-3">
          Endpoints ({suite.endpoints.length})
        </h2>

        {suite.endpoints.length === 0 ? (
          <p className="text-muted-foreground text-sm py-10 text-center border-2 border-dashed border-border rounded-xl">
            This suite has no endpoints.
          </p>
        ) : (
          <div className="space-y-3 stagger-in">
            {suite.endpoints.map((ep) => (
              <Card key={ep.id} className="px-4 py-4 space-y-3">
                <div className="flex items-start gap-3">
                  {/* Method pill — fixed-width column */}
                  <div className="shrink-0 w-16 mt-0.5">
                    <HttpMethodPill method={ep.method} />
                  </div>

                  {/* Path + name + description */}
                  <div className="min-w-0 flex-1">
                    <code className="font-mono text-sm break-all text-foreground">
                      {ep.path}
                    </code>
                    <div className="flex items-baseline gap-2 mt-0.5">
                      <span className="text-sm font-semibold shrink-0">
                        {ep.name}
                      </span>
                      {ep.description && (
                        <span className="text-xs text-muted-foreground truncate">
                          {ep.description}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Generate/regenerate tests + rendered test list */}
                <div className="pl-[76px]">
                  <EndpointTests
                    endpointId={ep.id}
                    environmentId={selectedEnvironmentId}
                    suiteResultsByTestId={
                      suiteRunState.kind === "done"
                        ? suiteRunState.resultsByTestId
                        : null
                    }
                    dependencyEdges={dependencyEdges}
                    testNamesById={testNamesById}
                    onTestsLoaded={handleTestsLoaded}
                    refreshToken={testsRefreshToken}
                  />
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* ---- AI Assistant (PRD §17-18, §25.3) ------------------------------- */}
      <ChatPanel
        suiteId={suite.id}
        testNamesById={testNamesById}
        onChangesApplied={() => setTestsRefreshToken((c) => c + 1)}
      />
    </div>
  );
}
