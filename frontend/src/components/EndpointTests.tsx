import { useEffect, useState, type ReactNode } from "react";
import {
  CircleAlert,
  CircleCheck,
  CircleX,
  Loader2,
  MinusCircle,
  Sparkles,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  type DependencyOut,
  type ExecutionOut,
  type ExecutionResultOut,
  type RequestSnapshot,
  type TestOut,
  type Uuid,
  type ValidationResultOut,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TestCategoryBadge } from "@/components/TestCategoryBadge";

// ---------------------------------------------------------------------------
// AI provider error message — shown to the user as the raw, unmodified
// text the backend received from the provider (ApiError.detail is
// TestGenerationError.message — see app/services/test_service.py), not a
// paraphrased/friendly version. `reason`/`resetAt`/`provider` are still
// available on ApiError for classification if ever needed, but are not
// used to rewrite the message.
// ---------------------------------------------------------------------------

function messageFromError(e: unknown): string {
  if (e instanceof ApiError) return e.detail || e.message;
  return "Something went wrong generating tests. Try again.";
}

// ---------------------------------------------------------------------------
// Plain-English mapping for execution failures. Two distinct failure paths
// land here:
//   1. Our own backend call to POST /tests/{id}/execute fails (ApiError —
//      e.g. the test or environment was deleted out from under us).
//   2. The engine ran but the real HTTP call to the target API itself
//      failed (ExecutionResult.status === "error", with a raw httpx
//      exception string in `.error`, e.g. "ConnectError: ...").
// Neither raw form should ever reach the user as-is.
// ---------------------------------------------------------------------------

function messageFromRunError(e: unknown): string {
  if (e instanceof ApiError) return e.detail || e.message;
  return "Couldn't run the test. Try again.";
}

function messageFromEngineError(raw: string): string {
  const text = raw.toLowerCase();
  if (text.includes("connect")) {
    return "Couldn't reach the API. Check the environment's base URL.";
  }
  if (text.includes("timeout") || text.includes("timed out")) {
    return "The API took too long to respond. Check the environment's base URL, or try again.";
  }
  if (text.includes("ssl") || text.includes("certificate")) {
    return "Couldn't establish a secure connection to the API. Check the environment's base URL.";
  }
  return "The request to the API failed. Check the environment's configuration and try again.";
}

// ---------------------------------------------------------------------------
// Plain-English reason a test was skipped during a suite run — walks the
// suite's dependency edges to name the specific test(s) that didn't pass,
// rather than showing the backend's generic "skipped (dependency failed)".
// ---------------------------------------------------------------------------

function computeSkipReason(
  testId: Uuid,
  suiteResultsByTestId: Record<Uuid, ExecutionOut>,
  dependencyEdges: DependencyOut[],
  testNamesById: Record<Uuid, string>
): string {
  const unmetDependencyIds = dependencyEdges
    .filter((edge) => edge.test_id === testId)
    .map((edge) => edge.depends_on_test_id)
    .filter((depId) => {
      const status = suiteResultsByTestId[depId]?.results[0]?.status;
      return status !== undefined && status !== "passed";
    });

  if (unmetDependencyIds.length === 0) {
    return "Skipped because a test it depends on didn't complete successfully.";
  }

  const names = unmetDependencyIds.map(
    (depId) => testNamesById[depId] ?? "a dependency"
  );
  return `Skipped because ${names.map((n) => `'${n}'`).join(", ")} failed.`;
}

// ---------------------------------------------------------------------------
// Waiting indicator — plain status text + a live elapsed-seconds counter so
// a long wait against the real LLM never reads as frozen. Free-tier NIM has
// real connection/queue overhead before generation even starts, so this can
// genuinely take a minute or two — the elapsed counter is what keeps that
// from looking broken.
// ---------------------------------------------------------------------------

function WaitingIndicator() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="flex items-center gap-3 rounded-lg border border-primary/20 bg-accent/50 px-3.5 py-3 text-sm animate-fade-in">
      <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden="true" />
      <div>
        <div className="text-foreground font-medium">Waiting for the AI to respond…</div>
        <div className="text-xs text-muted-foreground">
          This can take up to a minute or two.
        </div>
      </div>
      <span className="text-xs text-muted-foreground ml-auto shrink-0 font-mono tabular-nums">
        {elapsed}s so far
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Validation line — human-readable text (PRD §3.4 default view)
// ---------------------------------------------------------------------------

function ValidationLine({
  description,
  severity,
}: {
  description: string;
  severity: string;
}) {
  const dotColor = severity === "CRITICAL" ? "bg-danger" : "bg-warning";
  return (
    <li className="flex items-start gap-2 text-sm text-muted-foreground">
      <span
        className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dotColor}`}
        aria-hidden="true"
      />
      <span>{description}</span>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Run state + result badge — per-test execution status shown on the card
// ---------------------------------------------------------------------------

export type RunState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "error"; message: string }
  | {
      kind: "done";
      execution: ExecutionOut;
      result: ExecutionResultOut;
      /** Plain-English reason, set only when result.status === "skipped"
       *  (computed from the suite's dependency edges — see
       *  computeSkipReason). Falls back to a generic message if absent. */
      skipReason?: string;
    };

function ResultBadge({ runState }: { runState: RunState }) {
  if (runState.kind === "running") {
    return (
      <Badge variant="neutral" icon={<Loader2 className="animate-spin" />}>
        Running…
      </Badge>
    );
  }

  if (runState.kind === "error") {
    return (
      <Badge variant="warning" icon={<CircleAlert />}>
        Error
      </Badge>
    );
  }

  if (runState.kind === "done") {
    const { status } = runState.result;
    if (status === "passed") {
      return (
        <Badge variant="success" icon={<CircleCheck />} className="animate-scale-in">
          Passed
        </Badge>
      );
    }
    if (status === "failed") {
      return (
        <Badge variant="danger" icon={<CircleX />} className="animate-scale-in">
          Failed
        </Badge>
      );
    }
    if (status === "skipped") {
      return (
        <Badge variant="neutral" icon={<MinusCircle />} className="animate-scale-in">
          Skipped
        </Badge>
      );
    }
    return (
      <Badge variant="warning" icon={<CircleAlert />} className="animate-scale-in">
        Error
      </Badge>
    );
  }

  return null;
}

// ---------------------------------------------------------------------------
// One generated test card — clicking the body opens the full detail view;
// the Run button and result badge live in a separate footer row so they're
// not nested inside that button.
// ---------------------------------------------------------------------------

function TestCard({
  test,
  environmentId,
  runState,
  onClick,
  onRun,
}: {
  test: TestOut;
  environmentId: Uuid | null;
  runState: RunState;
  onClick: () => void;
  onRun: () => void;
}) {
  const running = runState.kind === "running";
  const runDisabled = !environmentId || running;

  return (
    <Card className="p-3.5 space-y-2.5 hover:border-primary/40 hover:shadow-[var(--shadow-card-hover)] transition-all duration-200">
      <button
        type="button"
        onClick={onClick}
        className="w-full text-left space-y-2 cursor-pointer"
      >
        <div className="flex items-start justify-between gap-2">
          <span className="text-sm font-semibold">{test.name}</span>
          <TestCategoryBadge category={test.category} />
        </div>
        {test.validations.length > 0 && (
          <ul className="space-y-1">
            {test.validations.map((v, i) => (
              <ValidationLine
                key={v.id ?? i}
                description={v.description}
                severity={v.severity}
              />
            ))}
          </ul>
        )}
      </button>

      <div className="flex items-center justify-between gap-2 pt-2.5 mt-1 border-t border-border/70">
        <span
          title={
            !environmentId
              ? "Select an environment above to run this test"
              : undefined
          }
        >
          <Button
            size="sm"
            variant="outline"
            onClick={onRun}
            disabled={runDisabled}
          >
            {running ? "Running…" : "Run"}
          </Button>
        </span>
        <ResultBadge runState={runState} />
      </div>

      {runState.kind === "error" && (
        <p className="text-xs text-destructive">{runState.message}</p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Test detail view — full, read-only info for one generated test.
// Rendered as a modal overlay so it works the same regardless of where in
// the page the triggering card sits.
// ---------------------------------------------------------------------------

function KeyValueTable({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">(none)</p>;
  }
  return (
    <table className="w-full text-sm border-collapse">
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key} className="border-t border-border first:border-t-0">
            <td className="py-1 pr-3 font-mono text-xs text-muted-foreground align-top whitespace-nowrap">
              {key}
            </td>
            <td className="py-1 font-mono text-xs break-all">
              {typeof value === "string" ? value : JSON.stringify(value)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DetailSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-1.5">
      <h4 className="text-eyebrow">
        {title}
      </h4>
      {children}
    </section>
  );
}

// The test's plan for one validation — what it checks and what it expects.
// Always rendered regardless of run state, so "what will this test check"
// is answerable before the user ever clicks Run.
function ExpectedValidationLine({ v }: { v: TestOut["validations"][number] }) {
  const dotColor = v.severity === "CRITICAL" ? "bg-danger" : "bg-warning";
  return (
    <li className="rounded-lg border border-border p-2.5 space-y-1 bg-card/50">
      <div className="flex items-start gap-2">
        <span
          className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dotColor}`}
          aria-hidden="true"
        />
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm">{v.description}</div>
          <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground font-mono">
            <span>type={v.type}</span>
            <span>severity={v.severity}</span>
            {v.target && <span>target={v.target}</span>}
            {v.expected !== null && v.expected !== undefined && (
              <span>expected={JSON.stringify(v.expected)}</span>
            )}
          </div>
          {v.enforcement === "informational" && (
            <p className="text-xs text-muted-foreground italic">
              Not counted — field name was not verified against a real response.
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

// The real outcome for one validation, from the test's last run. result is
// undefined only when this validation has no matching entry in
// validation_results at all (shouldn't happen once a result exists, but
// typed loosely) — the "not run yet" case is handled by the caller, which
// doesn't render this component until a result exists.
//
// result.id may be null (the backend types it loosely) even though v.id is
// a plain string on the plan-level validation — match by list index at the
// call site instead of by id, since the engine evaluates validations in
// list order, producing exactly one result per plan entry.
function ActualValidationLine({
  v,
  result,
}: {
  v: TestOut["validations"][number];
  result: ValidationResultOut;
}) {
  return (
    <li className="rounded-lg border border-border p-2.5 space-y-1 bg-card/50">
      <div className="flex items-start gap-2">
        {result.passed ? (
          <CircleCheck className="h-4 w-4 shrink-0 text-success mt-0.5" aria-hidden="true" />
        ) : (
          <CircleX className="h-4 w-4 shrink-0 text-danger mt-0.5" aria-hidden="true" />
        )}
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm">{v.description}</div>
          <div
            className={`text-xs font-mono break-all ${result.passed ? "text-muted-foreground" : "text-danger"}`}
          >
            actual={JSON.stringify(result.actual)}
            {result.error && <> — {result.error}</>}
          </div>
        </div>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Response section — shown once a result exists. Two distinct outcomes:
//   - response_snapshot present: the real API responded (status + pretty
//     body), regardless of whether validations passed.
//   - response_snapshot null: the HTTP call itself never got a response
//     (connection failure, timeout, etc.) — show the plain-English message
//     instead of the raw httpx exception text.
// ---------------------------------------------------------------------------

// Shows the fully resolved request that was actually sent (base_url + path,
// {{variable}} substitution, environment auth/default headers merged in) —
// distinct from the static plan shown before a run, which is what the test
// *would* send before environment resolution.
function ActualRequestDetail({ snapshot }: { snapshot: RequestSnapshot }) {
  const bodyText =
    snapshot.body === null || snapshot.body === undefined
      ? null
      : typeof snapshot.body === "string"
        ? snapshot.body
        : JSON.stringify(snapshot.body, null, 2);

  return (
    <div className="rounded-lg border border-border p-3 space-y-3 bg-card/50">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono font-semibold text-primary">{snapshot.method}</span>
        <span className="font-mono break-all">{snapshot.url}</span>
      </div>
      <div>
        <div className="text-xs text-muted-foreground mb-1">Headers</div>
        <KeyValueTable data={snapshot.headers} />
      </div>
      <div>
        <div className="text-xs text-muted-foreground mb-1">Query params</div>
        <KeyValueTable data={snapshot.params} />
      </div>
      <div>
        <div className="text-xs text-muted-foreground mb-1">Body</div>
        {bodyText === null ? (
          <p className="text-sm text-muted-foreground">(no body)</p>
        ) : (
          <pre className="text-xs font-mono bg-muted rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words">
            {bodyText}
          </pre>
        )}
      </div>
    </div>
  );
}

function ResponseSection({ result }: { result: ExecutionResultOut }) {
  if (!result.response_snapshot) {
    return (
      <div className="rounded-lg border border-danger-border bg-danger-bg p-3">
        <p className="text-sm text-danger">
          {messageFromEngineError(result.error ?? "")}
        </p>
      </div>
    );
  }

  const { status_code, body } = result.response_snapshot;
  const bodyText =
    body === null || body === undefined
      ? null
      : typeof body === "string"
        ? body
        : JSON.stringify(body, null, 2);

  return (
    <div className="rounded-lg border border-border p-3 space-y-3 bg-card/50">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-xs text-muted-foreground">Status</span>
        <span
          className={`font-mono font-semibold ${status_code >= 200 && status_code < 300 ? "text-success" : "text-danger"}`}
        >
          {status_code}
        </span>
        {result.duration_ms !== null && (
          <span className="text-xs text-muted-foreground ml-auto font-mono">
            {result.duration_ms} ms
          </span>
        )}
      </div>
      <div>
        <div className="text-xs text-muted-foreground mb-1">Body</div>
        {bodyText === null ? (
          <p className="text-sm text-muted-foreground">(empty body)</p>
        ) : (
          <pre className="text-xs font-mono bg-muted rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words max-h-64">
            {bodyText}
          </pre>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dependencies section (PRD §12 / §2.3) — what this test depends on (via
// {{variable}} references resolved before it runs), and what values it
// extracts for downstream tests to consume. Read-only here; adding/removing
// edges happens in the suite-level Dependencies panel (SuiteDetailPage),
// which has the full suite-wide test list needed to pick both ends of an
// edge — not just this one test's siblings.
// ---------------------------------------------------------------------------

function SourceBadge({ source }: { source: DependencyOut["source"] }) {
  return (
    <span className="text-xs font-mono text-muted-foreground">
      ({source === "auto" ? "auto-detected" : source === "user" ? "manual" : "ai"})
    </span>
  );
}

function TestDependenciesSection({
  test,
  dependencyEdges,
  testNamesById,
}: {
  test: TestOut;
  dependencyEdges: DependencyOut[];
  testNamesById: Record<Uuid, string>;
}) {
  const dependsOn = dependencyEdges.filter((e) => e.test_id === test.id);

  return (
    <div className="space-y-3">
      <div>
        <div className="text-xs text-muted-foreground mb-1">Depends on</div>
        {dependsOn.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing — this test doesn't depend on any other test.
          </p>
        ) : (
          <ul className="space-y-1">
            {dependsOn.map((edge) => (
              <li key={edge.id} className="text-sm flex items-center gap-2">
                <span>{testNamesById[edge.depends_on_test_id] ?? "(unknown test)"}</span>
                <SourceBadge source={edge.source} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <div className="text-xs text-muted-foreground mb-1">
          Extracts (passed downstream)
        </div>
        {test.extractions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing — this test doesn't extract any values.
          </p>
        ) : (
          <ul className="space-y-1">
            {test.extractions.map((ex, i) => (
              <li key={i} className="text-sm font-mono">
                <span className="text-foreground">{`{{${ex.name}}}`}</span>
                <span className="text-muted-foreground"> ← {ex.source}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function TestDetailPanel({
  test,
  runState,
  onClose,
  dependencyEdges,
  testNamesById,
}: {
  test: TestOut;
  runState: RunState;
  onClose: () => void;
  /** All dependency edges for the suite (PRD §12) — filtered here to just
   *  this test's "depends on" edges. */
  dependencyEdges?: DependencyOut[];
  /** test_id -> name, so a dependency can be shown by name rather than id. */
  testNamesById?: Record<Uuid, string>;
}) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const bodyText =
    test.body === null || test.body === undefined
      ? null
      : typeof test.body === "string"
        ? test.body
        : JSON.stringify(test.body, null, 2);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-end bg-black/50 backdrop-blur-[2px] animate-fade-in"
      onClick={onClose}
    >
      <div
        className="h-full w-full max-w-lg overflow-y-auto bg-card border-l border-border shadow-[var(--shadow-panel)] p-5 space-y-5 animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1.5 min-w-0">
            <h3 className="text-base font-bold break-words tracking-tight">{test.name}</h3>
            <TestCategoryBadge category={test.category} />
          </div>
          <Button size="icon" variant="ghost" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <DetailSection
          title={runState.kind === "done" ? "Request (as sent)" : "Request (planned)"}
        >
          {runState.kind === "done" ? (
            <ActualRequestDetail snapshot={runState.result.request_snapshot} />
          ) : (
            <div className="rounded-lg border border-border p-3 space-y-3 bg-card/50">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-mono font-semibold text-primary">{test.method}</span>
                <span className="font-mono break-all">{test.path}</span>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Headers</div>
                <KeyValueTable data={test.headers} />
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">
                  Query params
                </div>
                <KeyValueTable data={test.query_params} />
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Body</div>
                {bodyText === null ? (
                  <p className="text-sm text-muted-foreground">(no body)</p>
                ) : (
                  <pre className="text-xs font-mono bg-muted rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words">
                    {bodyText}
                  </pre>
                )}
              </div>
            </div>
          )}
        </DetailSection>

        {runState.kind === "done" && runState.result.status === "skipped" && (
          <DetailSection title="Response — Skipped">
            <div className="rounded-lg border border-neutral-border bg-neutral-bg p-3">
              <p className="text-sm text-neutral">
                {runState.skipReason ??
                  "Skipped because a test it depends on didn't complete successfully."}
              </p>
            </div>
          </DetailSection>
        )}

        {runState.kind === "done" && runState.result.status !== "skipped" && (
          <DetailSection
            title={`Response — ${runState.result.status === "passed" ? "Passed" : runState.result.status === "failed" ? "Failed" : "Error"}`}
          >
            <ResponseSection result={runState.result} />
          </DetailSection>
        )}

        {runState.kind === "error" && (
          <DetailSection title="Response">
            <div className="rounded-lg border border-danger-border bg-danger-bg p-3">
              <p className="text-sm text-danger">{runState.message}</p>
            </div>
          </DetailSection>
        )}

        <DetailSection title="Dependencies">
          <TestDependenciesSection
            test={test}
            dependencyEdges={dependencyEdges ?? []}
            testNamesById={testNamesById ?? {}}
          />
        </DetailSection>

        <DetailSection title={`Validations (${test.validations.length})`}>
          {test.validations.length === 0 ? (
            <p className="text-sm text-muted-foreground">(none)</p>
          ) : (
            <div className="grid grid-cols-1 gap-4 [@media(min-width:900px)]:grid-cols-2">
              <div className="min-w-0 space-y-1.5">
                <h5 className="text-eyebrow">Expected</h5>
                <ul className="space-y-1.5">
                  {test.validations.map((v, i) => (
                    <ExpectedValidationLine key={v.id ?? i} v={v} />
                  ))}
                </ul>
              </div>
              <div className="min-w-0 space-y-1.5">
                <h5 className="text-eyebrow">Actual</h5>
                {runState.kind === "done" && runState.result.status !== "skipped" ? (
                  <ul className="space-y-1.5">
                    {test.validations.map((v, i) => (
                      <ActualValidationLine
                        key={v.id ?? i}
                        v={v}
                        result={runState.result.validation_results[i]}
                      />
                    ))}
                  </ul>
                ) : (
                  <p className="rounded-lg border border-dashed border-border p-2.5 text-sm text-muted-foreground">
                    {runState.kind === "done" && runState.result.status === "skipped"
                      ? "This test was skipped — no results."
                      : "Run this test to see actual results here."}
                  </p>
                )}
              </div>
            </div>
          )}
        </DetailSection>

        <DetailSection title="AI confidence & notes">
          <div className="rounded-lg border border-border p-3 space-y-2 bg-card/50">
            <div className="text-sm flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              Confidence:{" "}
              <span className="font-mono font-semibold">
                {test.confidence.toFixed(2)}
              </span>
            </div>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">
              {test.ai_notes ?? "(no notes provided)"}
            </p>
          </div>
        </DetailSection>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component — one per endpoint
// ---------------------------------------------------------------------------

type GenerationStatus = "idle" | "waiting" | "success" | "error";

export function EndpointTests({
  endpointId,
  environmentId,
  suiteResultsByTestId,
  dependencyEdges,
  testNamesById,
  onTestsLoaded,
  refreshToken,
}: {
  endpointId: Uuid;
  environmentId: Uuid | null;
  /** Set by a suite-level "Run Suite" execution — maps test_id to its
   *  ExecutionOut. Null/undefined outside of a suite run. */
  suiteResultsByTestId?: Record<Uuid, ExecutionOut> | null;
  /** All dependency edges for the suite — used to explain *why* a skipped
   *  test was skipped (which dependency didn't pass). */
  dependencyEdges?: DependencyOut[];
  /** test_id -> test name, aggregated across every endpoint in the suite
   *  (via onTestsLoaded below), so a skip reason can name the specific
   *  test that failed even if it belongs to a different endpoint. */
  testNamesById?: Record<Uuid, string>;
  /** Reports this endpoint's tests up to the suite page once (re)loaded,
   *  so it can maintain the suite-wide testNamesById map. */
  onTestsLoaded?: (endpointId: Uuid, tests: TestOut[]) => void;
  /** Bump this (e.g. a counter) to force a refetch of this endpoint's
   *  tests — used after the chat assistant reports a change, so an
   *  updated validation/body shows up without a manual page reload. */
  refreshToken?: number;
}) {
  const [initialLoading, setInitialLoading] = useState(true);
  const [tests, setTests] = useState<TestOut[] | null>(null);
  const [status, setStatus] = useState<GenerationStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedTest, setSelectedTest] = useState<TestOut | null>(null);
  const [runStates, setRunStates] = useState<Record<Uuid, RunState>>({});

  useEffect(() => {
    let cancelled = false;
    // Only show the loading skeleton on the very first fetch — a
    // refreshToken-triggered refetch (after a chat-assistant change)
    // should update the list quietly, not flash the whole card back to a
    // loading state.
    if (tests === null) setInitialLoading(true);
    api
      .listTests(endpointId)
      .then((data) => {
        if (!cancelled) setTests(data);
      })
      .catch(() => {
        // Silent — an empty/failed initial fetch just means the user can
        // still click "Generate Tests"; no need to block on it.
        if (!cancelled) setTests(null);
      })
      .finally(() => {
        if (!cancelled) setInitialLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpointId, refreshToken]);

  useEffect(() => {
    if (tests) onTestsLoaded?.(endpointId, tests);
    // onTestsLoaded intentionally omitted: the parent passes a stable
    // callback identity per its own memoization needs, and including it
    // here would risk re-firing on every parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpointId, tests]);

  // Merge a completed suite-level run into this endpoint's own runStates —
  // same badge/detail-panel rendering path as a single-test "Run".
  useEffect(() => {
    if (!tests || !suiteResultsByTestId) return;
    setRunStates((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const test of tests) {
        const execution = suiteResultsByTestId[test.id];
        const result = execution?.results[0];
        if (!execution || !result) continue;
        next[test.id] = {
          kind: "done",
          execution,
          result,
          skipReason:
            result.status === "skipped"
              ? computeSkipReason(
                  test.id,
                  suiteResultsByTestId,
                  dependencyEdges ?? [],
                  testNamesById ?? {}
                )
              : undefined,
        };
        changed = true;
      }
      return changed ? next : prev;
    });
    // dependencyEdges/testNamesById deliberately excluded: they're derived
    // alongside suiteResultsByTestId on every suite run and would always
    // equal a fresh object identity, re-triggering this merge for no
    // reason — suiteResultsByTestId changing is what actually matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tests, suiteResultsByTestId]);

  function runGenerate() {
    if (
      hasTests &&
      !confirm(
        "This replaces all current tests for this endpoint, including any manual or chat-based edits. Continue?"
      )
    ) {
      return;
    }
    setStatus("waiting");
    setErrorMessage(null);
    api
      .generateTests(endpointId)
      .then((data) => {
        setTests(data);
        setStatus("success");
      })
      .catch((e: unknown) => {
        setErrorMessage(messageFromError(e));
        setStatus("error");
      });
  }

  function runTest(test: TestOut) {
    if (!environmentId) return;
    setRunStates((prev) => ({ ...prev, [test.id]: { kind: "running" } }));
    api
      .executeTest(test.id, environmentId)
      .then((execution) => {
        const result = execution.results[0];
        setRunStates((prev) => ({
          ...prev,
          [test.id]: result
            ? { kind: "done", execution, result }
            : { kind: "error", message: "The test ran but returned no result." },
        }));
      })
      .catch((e: unknown) => {
        setRunStates((prev) => ({
          ...prev,
          [test.id]: { kind: "error", message: messageFromRunError(e) },
        }));
      });
  }

  if (initialLoading) {
    return <div className="h-9 w-40 rounded-lg bg-muted animate-pulse" />;
  }

  const hasTests = tests !== null && tests.length > 0;
  const waiting = status === "waiting";

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Button
          size="sm"
          variant={hasTests ? "outline" : "brand"}
          onClick={runGenerate}
          disabled={waiting}
        >
          {!hasTests && <Sparkles className="h-3.5 w-3.5" />}
          {waiting
            ? "Generating…"
            : hasTests
              ? "Regenerate Tests"
              : "Generate Tests"}
        </Button>
        {hasTests && status !== "success" && !waiting && (
          <span className="text-xs text-muted-foreground">
            {tests!.length} test{tests!.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {waiting && <WaitingIndicator />}

      {status === "success" && (
        <p className="text-sm font-medium text-success flex items-center gap-1.5 animate-fade-in">
          <CircleCheck className="h-4 w-4" />
          Done! Generated {tests?.length ?? 0} test
          {tests?.length !== 1 ? "s" : ""}.
        </p>
      )}

      {status === "error" && (
        <div className="rounded-lg border border-danger-border bg-danger-bg px-3 py-2.5">
          <p className="text-sm text-danger">{errorMessage}</p>
          <Button size="sm" variant="outline" className="mt-2" onClick={runGenerate}>
            Try Again
          </Button>
        </div>
      )}

      {!waiting && hasTests && (
        <div className="space-y-2.5 stagger-in">
          {tests!.map((t) => (
            <TestCard
              key={t.id}
              test={t}
              environmentId={environmentId}
              runState={runStates[t.id] ?? { kind: "idle" }}
              onClick={() => setSelectedTest(t)}
              onRun={() => runTest(t)}
            />
          ))}
        </div>
      )}

      {selectedTest && (
        <TestDetailPanel
          test={selectedTest}
          runState={runStates[selectedTest.id] ?? { kind: "idle" }}
          onClose={() => setSelectedTest(null)}
          dependencyEdges={dependencyEdges}
          testNamesById={testNamesById}
        />
      )}
    </div>
  );
}
