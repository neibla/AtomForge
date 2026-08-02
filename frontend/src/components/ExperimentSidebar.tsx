import { useEffect, useMemo, useRef, useState } from "react";
import {
  FlaskConical,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCcw,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { experimentTitle } from "@/lib/experimentPresentation";
import type { RunRecordResponse } from "@/types";

interface ExperimentSidebarProps {
  runs: RunRecordResponse[];
  selectedId: string | null;
  isLoading: boolean;
  isRefreshing: boolean;
  onSelect: (experimentId: string) => void;
  onRefresh: () => void;
  onDelete: (experimentId: string) => void;
  onNewExperiment: () => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

type RunFilter = "ALL" | "ACTIVE" | "COMPLETED" | "ATTENTION";

const RUN_FILTERS: Array<{ value: RunFilter; label: string }> = [
  { value: "ALL", label: "All" },
  { value: "ACTIVE", label: "Active" },
  { value: "COMPLETED", label: "Done" },
  { value: "ATTENTION", label: "Issues" },
];

function matchesFilter(run: RunRecordResponse, filter: RunFilter) {
  if (filter === "ACTIVE")
    return run.state === "QUEUED" || run.state === "RUNNING";
  if (filter === "COMPLETED") return run.state === "COMPLETED";
  if (filter === "ATTENTION")
    return run.state === "FAILED" || run.state === "PARTIAL";
  return true;
}

function formatRunTime(value: string) {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return "Unknown time";

  const today = new Date();
  const isToday =
    timestamp.getDate() === today.getDate() &&
    timestamp.getMonth() === today.getMonth() &&
    timestamp.getFullYear() === today.getFullYear();

  return new Intl.DateTimeFormat(undefined, {
    ...(isToday ? {} : { month: "short", day: "numeric" }),
    hour: "numeric",
    minute: "2-digit",
  }).format(timestamp);
}

function statusDotClass(state: RunRecordResponse["state"]) {
  if (state === "COMPLETED") return "bg-[#79c28a]";
  if (state === "FAILED") return "bg-[#e18d87]";
  if (state === "PARTIAL") return "bg-[#d8a867]";
  return "bg-[#e9a45e] shadow-[0_0_0_3px_rgba(233,164,94,0.13)]";
}

function RailTooltip({ children }: { children: string }) {
  return (
    <span
      role="tooltip"
      className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-md border border-[#344b55] bg-[#0b151b] px-2.5 py-1.5 text-[11px] font-medium text-[#edf1eb] opacity-0 shadow-xl transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100"
    >
      {children}
    </span>
  );
}

export function ExperimentSidebar({
  runs,
  selectedId,
  isLoading,
  isRefreshing,
  onSelect,
  onRefresh,
  onDelete,
  onNewExperiment,
  collapsed,
  onToggleCollapsed,
}: ExperimentSidebarProps) {
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<RunFilter>("ALL");
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (window.matchMedia("(min-width: 1024px)").matches) {
          if (collapsed) onToggleCollapsed();
        } else {
          setIsMobileOpen(true);
        }
        window.setTimeout(() => searchInputRef.current?.focus(), 180);
      }
      if (event.key === "Escape") setIsMobileOpen(false);
    }

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [collapsed, onToggleCollapsed]);

  const sortedRuns = useMemo(() => {
    const ordered = [...runs].sort(
      (left, right) =>
        new Date(right.updated_at).getTime() -
        new Date(left.updated_at).getTime(),
    );

    // Reruns intentionally get immutable ids, but they often
    // share the same human-facing title. Keep the newest run in the sidebar;
    // older evidence remains available through its direct URL and storage.
    const seenTitles = new Set<string>();
    return ordered.filter((run) => {
      const title = experimentTitle(run.experiment_id).trim().toLowerCase();
      if (seenTitles.has(title)) return false;
      seenTitles.add(title);
      return true;
    });
  }, [runs]);

  const normalizedQuery = query.trim().toLowerCase();
  const visibleRuns = sortedRuns.filter((run) => {
    const matchesQuery =
      !normalizedQuery ||
      experimentTitle(run.experiment_id).toLowerCase().includes(normalizedQuery) ||
      run.experiment_id.toLowerCase().includes(normalizedQuery) ||
      run.parent_experiment_id?.toLowerCase().includes(normalizedQuery);
    return matchesQuery && matchesFilter(run, filter);
  });
  const activeCount = sortedRuns.filter(
    (run) => run.state === "QUEUED" || run.state === "RUNNING",
  ).length;

  function selectRun(experimentId: string) {
    onSelect(experimentId);
    setIsMobileOpen(false);
  }

  function startNewExperiment() {
    setIsMobileOpen(false);
    onNewExperiment();
  }

  function revealSearch() {
    if (collapsed) onToggleCollapsed();
    window.setTimeout(() => searchInputRef.current?.focus(), 180);
  }

  const expandedPanel = (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-[4.5rem] shrink-0 items-center gap-3 px-3.5">
        <img
          src="/favicon.png"
          alt=""
          className="h-9 w-9 shrink-0 rounded-[0.7rem] object-cover ring-1 ring-[#314751]"
        />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-[#eef2ed]">
            AtomForge
          </h1>
          <p className="mt-0.5 truncate text-[10px] text-[#70868f]">
            Research workspace
          </p>
        </div>
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label="Collapse sidebar"
          title="Collapse sidebar"
          className="hidden rounded-lg p-2 text-[#81959d] transition hover:bg-[#1a2a32] hover:text-[#edf1eb] focus-visible:outline-2 focus-visible:outline-[#d5794f] lg:block"
        >
          <PanelLeftClose className="h-[18px] w-[18px]" />
        </button>
        <button
          type="button"
          onClick={() => setIsMobileOpen(false)}
          aria-label="Close navigation"
          className="rounded-lg p-2 text-[#81959d] transition hover:bg-[#1a2a32] hover:text-[#edf1eb] lg:hidden"
        >
          <X className="h-[18px] w-[18px]" />
        </button>
      </header>

      <div className="shrink-0 px-2.5 pb-2">
        <button
          type="button"
          onClick={startNewExperiment}
          className="group flex h-11 w-full items-center gap-3 rounded-xl bg-[#b75d3c] px-3.5 text-left text-[13px] font-semibold text-[#fff8f2] transition duration-150 hover:bg-[#cb6d49] active:scale-[0.985] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#ed9a70]"
        >
          <Plus className="h-[18px] w-[18px] transition-transform duration-200 group-hover:rotate-90" />
          New experiment
        </button>
      </div>

      <div className="mx-3 border-t border-[#263b44]" />

      <section
        aria-label="Experiments"
        className="flex min-h-0 flex-1 flex-col pt-3"
      >
        <div className="flex shrink-0 items-center justify-between px-4">
          <div className="flex items-center gap-2">
            <FlaskConical
              className="h-3.5 w-3.5 text-[#70868f]"
              aria-hidden="true"
            />
            <h2 className="text-[10px] font-semibold uppercase tracking-[0.15em] text-[#82969e]">
              Experiments
            </h2>
            <span className="text-[10px] tabular-nums text-[#536b74]">
              {sortedRuns.length}
            </span>
          </div>
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            aria-label="Refresh experiments"
            title="Refresh experiments"
            className="rounded-md p-1.5 text-[#70868f] transition hover:bg-[#1a2a32] hover:text-[#d9e3df] disabled:opacity-40"
          >
            <RefreshCcw
              className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin")}
            />
          </button>
        </div>

        <div className="shrink-0 px-2.5 pb-2 pt-2">
          <label className="relative block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#657b84]" />
            <span className="sr-only">Search experiments</span>
            <input
              ref={searchInputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search experiments"
              className="h-9 w-full rounded-lg border border-transparent bg-[#13242c] pl-9 pr-12 text-[11px] text-[#e7eeea] outline-none transition placeholder:text-[#607681] hover:bg-[#172a33] focus:border-[#8f604d] focus:bg-[#101f27] focus:ring-2 focus:ring-[#d5794f]/10"
            />
            <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-[#344b55] px-1.5 py-0.5 text-[8px] text-[#70868f]">
              ⌘K
            </kbd>
          </label>
          <div className="mt-2 grid grid-cols-4 gap-1 rounded-lg bg-[#0b171d] p-1">
            {RUN_FILTERS.map((option) => (
              <button
                type="button"
                key={option.value}
                onClick={() => setFilter(option.value)}
                aria-pressed={filter === option.value}
                className={cn(
                  "rounded-md px-1 py-1.5 text-[9px] font-medium transition",
                  filter === option.value
                    ? "bg-[#22363f] text-[#f0c1a8] shadow-sm"
                    : "text-[#718790] hover:bg-[#16262e] hover:text-[#b9c7c8]",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {isLoading ? (
            <div
              className="space-y-2 px-1 pt-1"
              aria-label="Loading experiments"
            >
              {[0, 1, 2].map((item) => (
                <div
                  key={item}
                  className="h-[3.5rem] animate-pulse rounded-lg bg-[#14252d]"
                />
              ))}
            </div>
          ) : null}

          {!isLoading ? (
            <div className="space-y-0.5">
              {visibleRuns.map((run) => {
                const isSelected = run.experiment_id === selectedId;
                return (
                  <div
                    key={run.experiment_id}
                    className={cn(
                      "group relative flex min-h-[3.6rem] items-center rounded-lg transition-colors",
                      isSelected ? "bg-[#20343d]" : "hover:bg-[#172830]",
                    )}
                  >
                    {isSelected ? (
                      <span className="absolute inset-y-2 left-0 w-0.5 rounded-r-full bg-[#d5794f]" />
                    ) : null}
                    <button
                      type="button"
                      onClick={() => selectRun(run.experiment_id)}
                      aria-current={isSelected ? "page" : undefined}
                      className="flex min-w-0 flex-1 items-center gap-2.5 rounded-lg py-2 pl-3 pr-1 text-left focus-visible:outline-2 focus-visible:outline-[#d5794f]"
                    >
                      <span
                        className={cn(
                          "h-1.5 w-1.5 shrink-0 rounded-full",
                          statusDotClass(run.state),
                        )}
                      />
                      <span className="min-w-0 flex-1">
                        <span
                          title={run.experiment_id}
                          className={cn(
                            "block truncate text-[11px] font-medium",
                            isSelected ? "text-[#f4f4ee]" : "text-[#c0cece]",
                          )}
                        >
                          {experimentTitle(run.experiment_id)}
                        </span>
                        <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[9px] text-[#70868f]">
                          <span>{formatRunTime(run.updated_at)}</span>
                          <span aria-hidden="true">·</span>
                          <span
                            className="truncate font-mono"
                            title={run.experiment_id}
                          >
                            {run.experiment_id}
                          </span>
                        </span>
                      </span>
                    </button>
                    <div className="mr-1 flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                      <button
                        type="button"
                        onClick={() => onDelete(run.experiment_id)}
                        aria-label={`Delete experiment ${run.experiment_id}`}
                        title="Delete"
                        className="rounded-md p-1.5 text-[#82969e] transition hover:bg-[#3a252a] hover:text-[#e18d87]"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}

          {!isLoading && visibleRuns.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <FlaskConical className="mx-auto h-6 w-6 text-[#506872]" />
              <p className="mt-3 text-[11px] font-medium text-[#aababb]">
                {sortedRuns.length === 0
                  ? "No experiments yet"
                  : "No matching experiments"}
              </p>
              <p className="mt-1 text-[10px] leading-4 text-[#657b84]">
                {sortedRuns.length === 0
                  ? "Start a run to build your evidence trail."
                  : "Try a different search or status."}
              </p>
              {sortedRuns.length > 0 ? (
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    setFilter("ALL");
                  }}
                  className="mt-3 text-[10px] font-semibold text-[#e49a74] hover:text-[#ffc4a5]"
                >
                  Clear filters
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      <footer className="flex h-12 shrink-0 items-center gap-2 border-t border-[#263b44] px-4 text-[10px] text-[#70868f]">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            activeCount > 0 ? "bg-[#e9a45e]" : "bg-[#536b74]",
          )}
        />
        <span>
          {activeCount > 0 ? `${activeCount} active` : "Workspace idle"}
        </span>
        <span className="ml-auto tabular-nums">{sortedRuns.length} total</span>
      </footer>
    </div>
  );

  return (
    <>
      <aside className="sticky top-0 z-40 hidden h-screen min-h-0 self-start border-r border-[#2b424c] bg-[#0d1a21] lg:block">
        {collapsed ? (
          <div className="flex h-full flex-col items-center py-3">
            <button
              type="button"
              onClick={onToggleCollapsed}
              aria-label="Expand sidebar"
              className="group relative flex h-11 w-11 items-center justify-center rounded-xl transition hover:bg-[#192a32] focus-visible:outline-2 focus-visible:outline-[#d5794f]"
            >
              <img
                src="/favicon.png"
                alt=""
                className="h-9 w-9 rounded-[0.65rem] object-cover ring-1 ring-[#314751]"
              />
              <RailTooltip>AtomForge · expand sidebar</RailTooltip>
            </button>
            <div className="my-2 h-px w-7 bg-[#263b44]" />
            <button
              type="button"
              onClick={startNewExperiment}
              aria-label="New experiment"
              className="group relative flex h-11 w-11 items-center justify-center rounded-xl text-[#aab8b9] transition hover:bg-[#192a32] hover:text-[#f1b08e] focus-visible:outline-2 focus-visible:outline-[#d5794f]"
            >
              <Plus className="h-[19px] w-[19px]" />
              <RailTooltip>New experiment</RailTooltip>
            </button>
            <button
              type="button"
              onClick={revealSearch}
              aria-label="Search experiments"
              className="group relative flex h-11 w-11 items-center justify-center rounded-xl text-[#aab8b9] transition hover:bg-[#192a32] hover:text-[#f1b08e] focus-visible:outline-2 focus-visible:outline-[#d5794f]"
            >
              <FlaskConical className="h-[18px] w-[18px]" />
              <RailTooltip>Search experiments · ⌘K</RailTooltip>
            </button>
          </div>
        ) : (
          expandedPanel
        )}
      </aside>

      <header className="relative z-40 flex h-16 items-center border-b border-[#2b424c] bg-[#0d1a21] px-3 lg:hidden">
        <button
          type="button"
          onClick={() => setIsMobileOpen(true)}
          aria-label="Open navigation"
          aria-expanded={isMobileOpen}
          className="rounded-lg p-2 text-[#9babad] hover:bg-[#192a32] hover:text-[#eef2ed]"
        >
          <PanelLeftOpen className="h-5 w-5" />
        </button>
        <img
          src="/favicon.png"
          alt=""
          className="ml-2 h-8 w-8 rounded-lg object-cover"
        />
        <span className="ml-2.5 text-sm font-semibold text-[#eef2ed]">
          AtomForge
        </span>
        <button
          type="button"
          onClick={startNewExperiment}
          className="ml-auto flex h-9 items-center gap-1.5 rounded-lg bg-[#b75d3c] px-3 text-[11px] font-semibold text-[#fff8f2]"
        >
          <Plus className="h-3.5 w-3.5" /> New
        </button>
      </header>

      {isMobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setIsMobileOpen(false)}
            className="absolute inset-0 bg-[#050b0f]/70 backdrop-blur-[2px]"
          />
          <aside className="absolute inset-y-0 left-0 w-[min(20rem,88vw)] border-r border-[#2b424c] bg-[#0d1a21] shadow-2xl">
            {expandedPanel}
          </aside>
        </div>
      ) : null}
    </>
  );
}
