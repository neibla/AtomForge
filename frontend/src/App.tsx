import { lazy, Suspense, useEffect, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import {
  AlertTriangle,
  Box,
  FileText,
  GitBranch,
  LayoutDashboard,
  Loader2,
  Printer,
  RotateCcw,
  Settings2,
} from "lucide-react";

import {
  getListRunsQueryKey,
  useDeleteExperiment,
  useGetExperiment,
  useGetReport,
  useGetVisualizationCatalog,
  useListRuns,
  useRerunExperiment,
} from "@/api/default/default";
import { ExperimentGraphWorkspace } from "@/components/ExperimentGraphWorkspace";
import { ExperimentConfiguration } from "@/components/ExperimentConfiguration";
import { ExperimentCreationChooser } from "@/components/ExperimentCreationChooser";
import { ExperimentSummary } from "@/components/ExperimentSummary";
import { createInitialExperimentBundle } from "@/lib/experimentDraft";
import { ExperimentSidebar } from "@/components/ExperimentSidebar";
import { hasInspectableArtifacts } from "@/lib/results";
import { removeRun, upsertRun } from "@/lib/runCache";
import { experimentTitle } from "@/lib/experimentPresentation";
import { cn, errorMessage } from "@/lib/utils";
import type { ColorMode, DashboardView, RunRecordResponse } from "@/types";

const VisualizationHost = lazy(() => import("@/components/VisualizationHost"));

const DASHBOARD_VIEWS: DashboardView[] = [
  "graph",
  "visualization",
  "report",
  "configuration",
];
const ACTIVE_EXPERIMENT_SECTIONS = [
  { id: "graph" as const, icon: GitBranch, label: "Workflow" },
  { id: "visualization" as const, icon: LayoutDashboard, label: "Results" },
  { id: "report" as const, icon: FileText, label: "Report" },
  { id: "configuration" as const, icon: Settings2, label: "Config" },
];

function readNavigation() {
  if (typeof window === "undefined") {
    return {
      selectedId: null,
      view: "graph" as DashboardView,
      isComposerOpen: false,
    };
  }
  const params = new URLSearchParams(window.location.search);
  const requestedView = params.get("view") as DashboardView | null;
  return {
    selectedId: params.get("experiment"),
    view:
      requestedView && DASHBOARD_VIEWS.includes(requestedView)
        ? requestedView
        : "graph",
    isComposerOpen: params.get("new") === "1",
  };
}

function updateNavigation(
  changes: Partial<{
    experiment: string | null;
    view: DashboardView;
    newRun: boolean;
  }>,
  mode: "push" | "replace" = "push",
) {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  if ("experiment" in changes) {
    if (changes.experiment) params.set("experiment", changes.experiment);
    else params.delete("experiment");
  }
  if ("view" in changes && changes.view) params.set("view", changes.view);
  if ("newRun" in changes) {
    if (changes.newRun) params.set("new", "1");
    else params.delete("new");
  }
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  window.history[mode === "push" ? "pushState" : "replaceState"]({}, "", url);
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function LoadingPanel({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-80 flex-col items-center justify-center gap-3 bg-[#101a20]">
      <Loader2 className="h-7 w-7 animate-spin text-indigo-500" />
      <p className="text-sm text-slate-500">{label}</p>
    </div>
  );
}

function Dashboard() {
  const queryClient = useQueryClient();
  const initialNavigation = readNavigation();
  const [selectedId, setSelectedId] = useState<string | null>(
    initialNavigation.selectedId,
  );
  const [view, setView] = useState<DashboardView>(initialNavigation.view);
  const [colorMode, setColorMode] = useState<ColorMode>("element");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isComposerOpen, setIsComposerOpen] = useState(
    initialNavigation.isComposerOpen,
  );
  const [creationMode, setCreationMode] = useState<"chooser" | "dag">(
    "chooser",
  );
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    function handlePopState() {
      const navigation = readNavigation();
      setSelectedId(navigation.selectedId);
      setView(navigation.view);
      setIsComposerOpen(navigation.isComposerOpen);
      setCreationMode("chooser");
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const runsQuery = useListRuns({
    query: {
      refetchInterval: ({ state: { data } }) =>
        Array.isArray(data) &&
        data.some((run) => run.state === "QUEUED" || run.state === "RUNNING")
          ? 2_000
          : false,
    },
  });
  const deleteExperimentMutation = useDeleteExperiment();
  const rerunExperimentMutation = useRerunExperiment();
  const runs = Array.isArray(runsQuery.data) ? runsQuery.data : [];
  const isNewExperimentDraft = isComposerOpen && creationMode === "dag";
  const isEditorMode = isNewExperimentDraft;
  const activeId = selectedId ?? runs[0]?.experiment_id ?? null;
  const activeRun = runs.find((run) => run.experiment_id === activeId) ?? null;
  const hasFinishedArtifact = hasInspectableArtifacts(activeRun?.state);
  const canRerun =
    activeRun !== null &&
    activeRun.state !== "QUEUED" &&
    activeRun.state !== "RUNNING";

  const bundleQuery = useGetExperiment(activeId as string, {
    query: { enabled: activeId !== null && hasFinishedArtifact },
  });
  const reportQuery = useGetReport(activeId as string, {
    query: {
      enabled: activeId !== null && hasFinishedArtifact && view === "report",
    },
  });
  const visualizationQuery = useGetVisualizationCatalog(activeId as string, {
    query: {
      enabled:
        activeId !== null && hasFinishedArtifact && view === "visualization",
    },
  });

  const bundle = bundleQuery.data ?? null;
  const scientificDecision = bundle?.scientific_decision ?? null;
  const visualizationCatalog = visualizationQuery.data ?? null;
  const activeError =
    runsQuery.error ??
    bundleQuery.error ??
    reportQuery.error ??
    visualizationQuery.error;

  async function refresh() {
    setIsRefreshing(true);
    try {
      await queryClient.invalidateQueries();
    } finally {
      setIsRefreshing(false);
    }
  }

  function cacheRun(run: RunRecordResponse) {
    queryClient.setQueryData<RunRecordResponse[]>(
      getListRunsQueryKey(),
      (current = []) => upsertRun(current, run),
    );
  }

  async function refreshRuns() {
    await queryClient.invalidateQueries({
      queryKey: getListRunsQueryKey(),
      refetchType: "active",
    });
  }

  async function handleSubmitted(run: RunRecordResponse) {
    cacheRun(run);
    setSelectedId(run.experiment_id);
    setIsComposerOpen(false);
    updateNavigation(
      { experiment: run.experiment_id, newRun: false },
      "replace",
    );
    await refreshRuns();
  }

  async function handleRerun() {
    if (!activeId || !canRerun || rerunExperimentMutation.isPending) return;
    if (!window.confirm(`Rerun ${experimentTitle(activeId)}?`)) return;

    setActionError(null);
    try {
      const nextRun = await rerunExperimentMutation.mutateAsync({
        id: activeId,
      });
      cacheRun(nextRun);
      setSelectedId(nextRun.experiment_id);
      setView("graph");
      updateNavigation(
        { experiment: nextRun.experiment_id, view: "graph" },
        "replace",
      );
      await refreshRuns();
    } catch (error) {
      setActionError(errorMessage(error, "Experiment rerun failed"));
    }
  }

  function selectExperiment(experimentId: string) {
    setSelectedId(experimentId);
    setIsComposerOpen(false);
    updateNavigation({ experiment: experimentId, newRun: false });
  }

  function changeView(nextView: DashboardView) {
    setView(nextView);
    updateNavigation({ view: nextView });
  }

  async function handleDelete(experimentId: string) {
    if (!window.confirm(`Delete experiment ${experimentId}?`)) return;
    try {
      await deleteExperimentMutation.mutateAsync({ id: experimentId });
      const remainingRuns = removeRun(runs, experimentId);
      queryClient.setQueryData(getListRunsQueryKey(), remainingRuns);
      if (selectedId === experimentId) {
        const nextId = remainingRuns[0]?.experiment_id ?? null;
        setSelectedId(nextId);
        updateNavigation({ experiment: nextId }, "replace");
      }
      await refreshRuns();
    } catch (error) {
      setActionError(errorMessage(error, "Experiment deletion failed"));
    }
  }

  function printReport() {
    const content = reportQuery.data?.content;
    if (!content) return;
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      setActionError(
        "The browser blocked the report window. Allow pop-ups to save a PDF.",
      );
      return;
    }
    printWindow.document.open();
    printWindow.document.write(content);
    printWindow.document.close();
    printWindow.focus();
    window.setTimeout(() => printWindow.print(), 250);
  }

  function openNewRun() {
    setIsComposerOpen(true);
    setCreationMode("chooser");
    updateNavigation({ newRun: true });
  }

  function closeNewRun() {
    setIsComposerOpen(false);
    updateNavigation({ newRun: false }, "replace");
  }

  function openDAGEditor() {
    setCreationMode("dag");
    setIsComposerOpen(true);
    updateNavigation({ newRun: true }, "replace");
  }

  return (
    <main
      className={cn(
        "app-shell grid min-h-screen grid-rows-[auto_auto] overflow-visible bg-[#0b141a] font-sans text-[#dce7e4] lg:grid-rows-[auto] lg:transition-[grid-template-columns] lg:duration-200 lg:ease-out",
        isSidebarCollapsed
          ? "lg:grid-cols-[4.5rem_minmax(0,1fr)]"
          : "lg:grid-cols-[16rem_minmax(0,1fr)]",
      )}
    >
      <ExperimentSidebar
        runs={runs}
        selectedId={activeId}
        isLoading={runsQuery.isLoading}
        isRefreshing={isRefreshing}
        onSelect={selectExperiment}
        onRefresh={refresh}
        onDelete={handleDelete}
        onNewExperiment={openNewRun}
        collapsed={isSidebarCollapsed}
        onToggleCollapsed={() =>
          setIsSidebarCollapsed((collapsed) => !collapsed)
        }
      />

      <section className="flex min-w-0 flex-col bg-[#101a20] lg:min-h-screen">
        <header className="flex min-h-14 flex-wrap items-center gap-x-5 gap-y-2 border-b border-[#35515e] bg-[#101d24] px-5 py-3 lg:px-8">
          <div className="min-w-0 flex-1 basis-44">
            <h2 className="truncate text-sm font-semibold text-[#f2f7f4]">
              {isEditorMode
                ? "DAG editor"
                : activeId
                  ? experimentTitle(activeId)
                  : "No experiment selected"}
            </h2>
            {!isEditorMode && activeId ? (
              <p className="mt-0.5 truncate font-mono text-[9px] text-[#70868f]">
                {activeId}
              </p>
            ) : null}
          </div>
          {!isEditorMode && activeRun ? (
            <button
              type="button"
              onClick={() => void handleRerun()}
              disabled={!canRerun || rerunExperimentMutation.isPending}
              className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[#6b5944] bg-[#2d2820] px-3 py-2 text-xs font-semibold text-[#e7bd7e] transition hover:border-[#d5794f] hover:bg-[#3a3022] hover:text-[#ffd5bd] disabled:cursor-not-allowed disabled:opacity-45"
            >
              <RotateCcw
                className={cn(
                  "h-3.5 w-3.5",
                  rerunExperimentMutation.isPending && "animate-spin",
                )}
              />
              {rerunExperimentMutation.isPending ? "Queueing…" : "Rerun"}
            </button>
          ) : null}
        </header>

        <nav
          aria-label={
            isNewExperimentDraft
              ? "New experiment modes"
              : "Active experiment sections"
          }
          className="flex min-h-14 items-stretch gap-1 overflow-x-auto border-b border-[#30464f] bg-[#0e1920] px-5 lg:px-8"
        >
          {isNewExperimentDraft ? (
            <>
              <div className="mr-2 flex items-center border-r border-[#30464f] pr-5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#d5794f]">
                  New experiment
                </span>
              </div>
              <button
                type="button"
                aria-current={isEditorMode ? "page" : undefined}
                onClick={openDAGEditor}
                className={cn(
                  "relative flex shrink-0 items-center gap-2 px-4 text-xs font-semibold transition-colors after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-[#d5794f]",
                  isEditorMode
                    ? "text-[#f3c4a8]"
                    : "text-[#91a5ad] hover:text-[#dce7e4] after:hidden",
                )}
              >
                <GitBranch className="h-3.5 w-3.5" /> Editor
              </button>
            </>
          ) : (
            <>
              {ACTIVE_EXPERIMENT_SECTIONS.map((section) => (
                <button
                  type="button"
                  key={section.id}
                  aria-current={view === section.id ? "page" : undefined}
                  onClick={() => changeView(section.id)}
                  className={cn(
                    "relative flex shrink-0 items-center gap-2 px-4 text-xs font-semibold transition-colors after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:origin-center after:scale-x-0 after:bg-[#d5794f] after:transition-transform",
                    view === section.id
                      ? "text-[#f3c4a8] after:scale-x-100"
                      : "text-[#91a5ad] hover:text-[#dce7e4]",
                  )}
                >
                  <section.icon className="h-3.5 w-3.5" />
                  {section.label}
                </button>
              ))}
              {activeRun ? (
                <div
                  className={cn(
                    "flex shrink-0 items-center gap-2 pl-5 text-[11px] font-medium text-[#91a5ad]",
                    activeId && hasFinishedArtifact ? "" : "ml-auto",
                  )}
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      activeRun.state === "COMPLETED"
                        ? "bg-[#79c28a]"
                        : activeRun.state === "FAILED"
                          ? "bg-[#e18d87]"
                          : "bg-[#d8a867]",
                    )}
                  />
                  {activeRun.state}
                </div>
              ) : null}
            </>
          )}
        </nav>

        {actionError ? (
          <p className="border-b border-rose-200 bg-rose-50 px-5 py-2 text-sm text-rose-700 lg:px-8">
            {actionError}
          </p>
        ) : null}

        <div className="flex flex-col overflow-visible">
          {!isEditorMode && bundle ? (
            <ExperimentSummary bundle={bundle} />
          ) : null}
          <div className="overflow-visible">
            {isEditorMode ? (
              <ExperimentGraphWorkspace
                bundle={createInitialExperimentBundle()}
                run={null}
                newExperiment
                onClose={closeNewRun}
                onSubmitted={handleSubmitted}
              />
            ) : activeError ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
                <AlertTriangle className="h-10 w-10 text-rose-400" />
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">
                    Artifact unavailable
                  </h3>
                  <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
                    {errorMessage(activeError, "Unknown request failure")}
                  </p>
                </div>
              </div>
            ) : !activeId ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-400">
                <Box className="h-10 w-10" />
                <p className="text-sm">No experiment artifacts found</p>
              </div>
            ) : activeRun && !hasFinishedArtifact ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
                {activeRun.state === "FAILED" ? (
                  <AlertTriangle className="h-10 w-10 text-rose-400" />
                ) : (
                  <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
                )}
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">
                    Run {activeRun.state.toLowerCase()}
                  </h3>
                  <p className="mt-2 max-w-xl font-mono text-xs leading-relaxed text-slate-500">
                    {activeRun.error ??
                      activeRun.call_id ??
                      "Waiting for a Modal worker assignment"}
                  </p>
                </div>
              </div>
            ) : bundleQuery.isLoading ? (
              <LoadingPanel label="Resolving result bundle" />
            ) : view === "graph" ? (
              bundle ? (
                <ExperimentGraphWorkspace
                  key={activeId}
                  bundle={bundle}
                  run={activeRun}
                  onSubmitted={handleSubmitted}
                />
              ) : (
                <LoadingPanel label="Resolving experiment graph" />
              )
            ) : view === "visualization" ? (
              visualizationQuery.isLoading ? (
                <LoadingPanel label="Loading visualization catalog" />
              ) : (
                <Suspense
                  fallback={
                    <LoadingPanel label="Loading visualization renderer" />
                  }
                >
                  <VisualizationHost
                    key={activeId}
                    catalog={visualizationCatalog}
                    experimentId={activeId as string}
                    colorMode={colorMode}
                    onColorModeChange={setColorMode}
                    metrics={bundle?.results.metrics}
                    decision={scientificDecision}
                  />
                </Suspense>
              )
            ) : view === "report" ? (
              reportQuery.isLoading ? (
                <LoadingPanel label="Loading evidence report" />
              ) : (
                <div className="min-h-[calc(100vh-8rem)] overflow-hidden bg-[#09151b] p-3 lg:p-5">
                  <div className="flex min-h-[calc(100vh-11rem)] flex-col gap-3">
                    <div className="flex shrink-0 items-center justify-between gap-3 rounded-lg border border-[#2b4b58] bg-[#101d24] px-3 py-2">
                      <p className="text-xs text-[#a7b4b3]">
                        Generated HTML report · print dialog can save it as PDF
                      </p>
                      <button
                        type="button"
                        onClick={printReport}
                        disabled={!reportQuery.data?.content}
                        className="flex items-center gap-1.5 rounded-md border border-[#d5794f] bg-[#462b20] px-3 py-1.5 text-xs font-semibold text-[#ffd5bd] transition hover:bg-[#593225] disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        <Printer className="h-3.5 w-3.5" /> Print / Save PDF
                      </button>
                    </div>
                    {reportQuery.data?.content ? (
                      <iframe
                        title={`Generated research report for ${activeId}`}
                        srcDoc={reportQuery.data.content}
                        className="min-h-[calc(100vh-14rem)] w-full flex-1 rounded-xl border border-[#2b4b58] bg-[#09151b] shadow-[0_18px_50px_rgba(0,0,0,0.22)]"
                        sandbox=""
                      />
                    ) : (
                      <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-[#91a5ad]">
                        Generated report unavailable
                      </div>
                    )}
                  </div>
                </div>
              )
            ) : bundle ? (
              <ExperimentConfiguration
                bundle={bundle}
              />
            ) : (
              <LoadingPanel label="Resolving experiment configuration" />
            )}
          </div>
        </div>
      </section>
      {isComposerOpen && creationMode === "chooser" ? (
        <ExperimentCreationChooser
          onClose={closeNewRun}
          onChooseDAG={openDAGEditor}
        />
      ) : null}
    </main>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Suspense
        fallback={
          <div className="flex h-screen w-screen items-center justify-center bg-slate-50 text-indigo-600">
            <Loader2 className="h-8 w-8 animate-spin" />
          </div>
        }
      >
        <Dashboard />
      </Suspense>
    </QueryClientProvider>
  );
}
