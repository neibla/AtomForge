import { useState, Suspense, useMemo } from "react";
import { 
  Zap, 
  RefreshCcw,
  CheckCircle2,
  History,
  Box,
  Loader2,
  FileText,
  Settings2,
  Table as TableIcon,
  HelpCircle,
  TrendingDown
} from "lucide-react";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  Cell,
  ScatterChart,
  Scatter,
  ReferenceLine
} from "recharts";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import AtomViewer from "@/components/AtomViewer";
import ReactMarkdown from "react-markdown";
import { cn } from "@/lib/utils";

const MODAL_API_URL = import.meta.env.VITE_MODAL_API_URL;

function DashboardContent() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [colorMode, setColorMode] = useState<"element" | "energy" | "defect">("element");
  const [view, setView] = useState<"viz" | "analysis" | "report" | "params" | "data">("viz");
  const [isRefreshingArchive, setIsRefreshingArchive] = useState(false);

  const { 
    data: experiments = [], 
    refetch: refreshExperiments, 
    isLoading: isHistoryLoading 
  } = useQuery({
    queryKey: ["experiments"],
    queryFn: async () => {
      const resp = await fetch(`${MODAL_API_URL}/experiments`);
      if (!resp.ok) throw new Error("History fetch failed");
      return resp.json();
    }
  });

  const { data: bundle, isLoading: isBundleLoading, refetch: refetchBundle } = useQuery({
    queryKey: ["experiment", selectedId],
    queryFn: async () => {
      if (!selectedId) return null;
      const resp = await fetch(`${MODAL_API_URL}/experiments/${selectedId}`);
      if (!resp.ok) throw new Error("Bundle fetch failed");
      return resp.json();
    },
    enabled: !!selectedId
  });

  const { data: reportMd, refetch: refetchReport } = useQuery({
    queryKey: ["report", selectedId],
    queryFn: async () => {
      if (!selectedId) return null;
      const resp = await fetch(`${MODAL_API_URL}/experiments/${selectedId}/report`);
      if (!resp.ok) throw new Error("Report fetch failed");
      return resp.json();
    },
    enabled: !!selectedId
  });

  const { data: atoms, isLoading: isVizLoading, refetch: refetchViz } = useQuery({
    queryKey: ["viz", selectedId],
    queryFn: async () => {
      if (!selectedId) return null;
      const resp = await fetch(`${MODAL_API_URL}/experiments/${selectedId}/viz`);
      if (!resp.ok) throw new Error("Viz fetch failed");
      return resp.json();
    },
    enabled: !!selectedId
  });

  const isLoading = isBundleLoading || isVizLoading;
  const report = bundle?.results;
  const spec = bundle?.spec;
  const analysis = bundle?.analysis;

  // Dynamic Metrics Extraction
  const modulusMetrics = useMemo(() => {
    if (!report?.metrics) return [];
    return Object.entries(report.metrics as Record<string, any>)
      .filter(([key]) => key.includes("youngs_modulus_gpa"))
      .map(([key, m]) => ({
        name: key.split("_")[1]?.toUpperCase() || key,
        val: m.val
      }));
  }, [report]);

  // Energy Distribution Histogram
  const energyStats = useMemo(() => {
    if (!atoms?.energies || atoms.energies.length === 0) return null;
    const sorted = [...atoms.energies].sort((a, b) => a - b);
    const min = sorted[0];
    const max = sorted[sorted.length - 1];
    const bins = 20;
    const step = (max - min) / bins;
    const histogram = Array.from({ length: bins }, (_, i) => {
      const start = min + i * step;
      const end = start + step;
      const count = atoms.energies!.filter((e: number) => e >= start && e < end).length;
      return { 
        name: `${start.toFixed(2)}`,
        count 
      };
    });
    return histogram;
  }, [atoms]);

  const hasEnergyData = !!(atoms?.energies && atoms.energies.length > 0);
  const hasDefectData = !!(atoms?.initial_positions && atoms.initial_positions.length === atoms.positions.length);

  const energyTrendData = useMemo(
    () =>
      (analysis?.energy_trend || []).map((row: any) => ({
        ...row,
        label: `${Math.round(row.energy_ev)} eV @ ${Math.round(row.temperature_K)}K`,
        defect_mean: row.mean_defects ?? 0,
      })),
    [analysis]
  );

  const temperatureTrendData = useMemo(
    () =>
      (analysis?.temperature_trend || []).map((row: any) => ({
        ...row,
        label: `${Math.round(row.temperature_K)}K @ ${Math.round(row.energy_ev)} eV`,
        defect_mean: row.mean_defects ?? 0,
      })),
    [analysis]
  );

  const selectedCondition = useMemo(() => {
    const pka = analysis?.pka_conditions || [];
    return [...pka].sort((a: any, b: any) => {
      const energyDelta = (b.energy_ev ?? 0) - (a.energy_ev ?? 0);
      if (energyDelta !== 0) return energyDelta;
      return (b.temperature_K ?? 0) - (a.temperature_K ?? 0);
    })[0] || null;
  }, [analysis]);

  const selectedTrialSeries = useMemo(() => {
    return (selectedCondition?.trial_defects || []).map((value: number, index: number) => ({
      trial: index + 1,
      defects: value,
    }));
  }, [selectedCondition]);

  const handleRefreshArchive = async () => {
    setIsRefreshingArchive(true);
    try {
      await Promise.all([
        refreshExperiments(),
        selectedId ? refetchBundle() : Promise.resolve(),
        selectedId ? refetchReport() : Promise.resolve(),
        selectedId ? refetchViz() : Promise.resolve(),
        selectedId ? queryClient.invalidateQueries({ queryKey: ["experiment", selectedId] }) : Promise.resolve(),
      ]);
    } finally {
      setIsRefreshingArchive(false);
    }
  };

  return (
    <main className="flex h-screen bg-[#050505] text-zinc-400 font-sans selection:bg-cyan-500/30 overflow-hidden">
      <div className="scanline fixed inset-0 pointer-events-none z-50 opacity-5" />

      {/* Sidebar: Experiment Browser */}
      <aside className="w-80 border-r border-white/5 flex flex-col z-20 bg-[#080808]">
        <div className="p-5 flex items-center gap-3 border-b border-white/5 bg-black/20">
          <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20 shadow-[0_0_15px_rgba(6,182,212,0.1)]">
            <Zap className="w-5 h-5 text-cyan-400" />
          </div>
          <h1 className="text-sm font-black tracking-[0.2em] text-white uppercase italic">AtomForge</h1>
        </div>

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="p-4 flex-1 flex flex-col overflow-hidden">
             <div className="flex items-center justify-between mb-4 px-1">
                <div className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
                  <History className="w-3 h-3" /> Cloud Archive
                </div>
                <button 
                  onClick={handleRefreshArchive}
                  disabled={isRefreshingArchive}
                  className={cn(
                    "text-cyan-500/60 hover:text-cyan-400 transition-all disabled:opacity-40 disabled:cursor-not-allowed",
                    (isHistoryLoading || isRefreshingArchive) && "animate-spin"
                  )}
                >
                  <RefreshCcw className="w-3 h-3" />
                </button>
             </div>
             
             <div className="flex-1 overflow-y-auto space-y-1.5 pr-2 custom-scrollbar">
                {(isHistoryLoading || isRefreshingArchive) && <div className="text-[10px] text-cyan-500/40 animate-pulse italic p-4 text-center bg-white/5 rounded-xl border border-white/5">Refreshing archive...</div>}
                {!isHistoryLoading && !isRefreshingArchive && experiments.length === 0 && <div className="text-[10px] text-zinc-600 italic text-center py-8">No artifacts found in volume.</div>}
                {experiments.map((id: string) => (
                  <button
                    key={id}
                    onClick={() => setSelectedId(id)}
                    className={cn(
                      "w-full text-left px-4 py-3 rounded-xl text-[10px] font-mono transition-all border group",
                      selectedId === id 
                        ? "bg-cyan-500/10 border-cyan-500/30 text-cyan-400 shadow-[0_0_20px_rgba(6,182,212,0.05)]" 
                        : "bg-transparent border-transparent text-zinc-500 hover:bg-white/5 hover:text-zinc-300"
                    )}
                  >
                    <div className="truncate">{id}</div>
                    <div className="text-[8px] opacity-0 group-hover:opacity-100 transition-opacity text-zinc-600">view logs &rarr;</div>
                  </button>
                ))}
             </div>
          </div>

          <div className="p-4 bg-black/40 border-t border-white/5">
            <div className="grid grid-cols-5 gap-2">
              {[
                { id: "viz", icon: Box, label: "Viz" },
                { id: "analysis", icon: TrendingDown, label: "Trends" },
                { id: "report", icon: FileText, label: "Log" },
                { id: "data", icon: TableIcon, label: "Data" },
                { id: "params", icon: Settings2, label: "Cfg" }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setView(tab.id as any)}
                  className={cn(
                    "flex flex-col items-center justify-center gap-1.5 py-3 rounded-xl border transition-all",
                    view === tab.id 
                      ? "bg-cyan-500/10 border-cyan-500/30 text-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.1)]" 
                      : "bg-transparent border-transparent text-zinc-600 hover:text-zinc-400"
                  )}
                >
                  <tab.icon className="w-3.5 h-3.5" />
                  <span className="text-[8px] font-bold uppercase tracking-tighter">{tab.label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <nav className="p-4 space-y-6 bg-[#080808] border-t border-white/5">
          <div className="space-y-3">
            <div className="flex justify-between items-center px-1">
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-[0.2em]">Visual Analysis</label>
              <HelpCircle className="w-3 h-3 text-zinc-600 cursor-help hover:text-zinc-400 transition-colors" />
            </div>
            <div className="flex p-1 bg-black/60 rounded-xl border border-white/5 gap-1">
              {["element", "energy", "defect"].map((v) => (
                <button 
                  key={v} 
                  disabled={(v === "energy" && !hasEnergyData) || (v === "defect" && !hasDefectData)}
                  onClick={() => setColorMode(v as any)}
                  className={cn(
                    "flex-1 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-widest transition-all relative", 
                    colorMode === v 
                      ? "bg-cyan-500 text-black shadow-[0_0_15px_rgba(6,182,212,0.4)]" 
                      : "text-zinc-600 hover:text-zinc-300 disabled:opacity-20 disabled:cursor-not-allowed"
                  )}
                >
                  {v}
                  {(v === "energy" && !hasEnergyData) || (v === "defect" && !hasDefectData) ? (
                    <div className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-zinc-800 border border-white/10" />
                  ) : null}
                </button>
              ))}
            </div>
            <div className="text-[8px] text-zinc-600 px-1 italic">
              {colorMode === "element" && "• Color by atomic species"}
              {colorMode === "energy" && (hasEnergyData ? "• Color by potential energy gradient" : "⚠️ Legacy result: No energy data available")}
              {colorMode === "defect" && (hasDefectData ? "• Color by displacement (Red=Defect)" : "⚠️ Legacy result: No initial positions available")}
            </div>
          </div>

          {report && (
            <div className="p-5 rounded-2xl bg-indigo-500/5 border border-indigo-500/10 space-y-4">
              <div className="flex items-center gap-2 text-[10px] font-bold text-indigo-400 uppercase tracking-[0.2em]">
                <CheckCircle2 className="w-4 h-4" /> Hypothesis Eval
              </div>
              <div className="space-y-3">
                {report.hypotheses.map((ev: any) => (
                  <div key={ev.id} className="space-y-2">
                    <div className="flex flex-col gap-1">
                      <div className="flex justify-between items-start gap-3">
                        <span className="text-[10px] text-zinc-300 font-medium leading-snug break-words">{ev.id}</span>
                        <span className={cn(
                          "text-[8px] font-bold px-2 py-0.5 rounded-full border shrink-0", 
                          ev.status === "PROVEN" 
                            ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400" 
                            : "bg-rose-500/10 border-rose-500/20 text-rose-400"
                        )}>{ev.status}</span>
                      </div>
                      <div className="text-[8px] text-zinc-600 uppercase tracking-widest">
                        Confidence: {Math.round((Number(ev.confidence) || 0) * 100)}%
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                       <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-indigo-500 shadow-[0_0_5px_#6366f1]"
                            style={{ width: `${Math.max(0, Math.min(100, Number(ev.confidence || 0) * 100))}%` }}
                          />
                       </div>
                       <div className="text-[9px] text-zinc-500 font-mono italic">{parseFloat(ev.value).toFixed(2)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </nav>
      </aside>

      {/* Main Viewport */}
      <section className="flex-1 flex flex-col relative bg-[#050505]">
        <div className="flex-1 relative overflow-hidden">
          {isLoading ? (
            <div className="h-full w-full flex flex-col items-center justify-center gap-6 bg-[#050505] z-50">
               <div className="relative">
                  <Loader2 className="w-12 h-12 text-cyan-500 animate-spin opacity-20" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Zap className="w-5 h-5 text-cyan-400 animate-pulse" />
                  </div>
               </div>
               <div className="text-[10px] font-mono text-cyan-500/60 animate-pulse uppercase tracking-[0.4em]">Resolving Molecular Dynamics...</div>
            </div>
          ) : !selectedId ? (
            <div className="h-full w-full flex flex-col items-center justify-center gap-4 text-zinc-700 bg-[radial-gradient(circle_at_center,_#111_0%,_#050505_100%)]">
               <Box className="w-12 h-12 opacity-10" />
               <p className="text-[11px] uppercase tracking-[0.3em] font-medium">Select an experiment to begin analysis</p>
            </div>
          ) : view === "viz" ? (
            <AtomViewer data={atoms} colorMode={colorMode} />
          ) : view === "analysis" ? (
            <div className="h-full overflow-y-auto px-12 py-16 custom-scrollbar">
              <div className="max-w-6xl mx-auto space-y-10">
                <header className="flex items-end justify-between border-b border-white/5 pb-6">
                  <div>
                    <h2 className="text-xs font-bold text-cyan-500 uppercase tracking-[0.4em] mb-2">Trend Validation</h2>
                    <p className="text-[10px] text-zinc-500 italic uppercase tracking-wider">Energy, temperature, and trial spread summaries</p>
                  </div>
                  <div className="flex gap-8">
                    <div className="flex flex-col items-end">
                      <span className="text-[8px] text-zinc-600 uppercase tracking-wider">PKA Conditions</span>
                      <span className="text-sm font-mono text-white">{analysis?.pka_conditions?.length || 0}</span>
                    </div>
                    <div className="flex flex-col items-end">
                      <span className="text-[8px] text-zinc-600 uppercase tracking-wider">Selected Set</span>
                      <span className="text-sm font-mono text-white">
                        {selectedCondition ? `${Math.round(selectedCondition.energy_ev)} eV @ ${Math.round(selectedCondition.temperature_K)}K` : "N/A"}
                      </span>
                    </div>
                  </div>
                </header>

                {!analysis?.pka_conditions?.length ? (
                  <div className="py-20 flex flex-col items-center justify-center gap-4 bg-white/[0.02] border border-white/5 rounded-[2rem]">
                    <TrendingDown className="w-12 h-12 opacity-10" />
                    <p className="text-[10px] uppercase tracking-widest text-zinc-600 font-bold text-center px-10 leading-loose">
                      No summary analytics available yet.
                      <br />
                      <span className="text-zinc-700 italic">Run a PKA experiment to populate the trend charts.</span>
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                    <div className="p-6 rounded-[2rem] bg-white/[0.02] border border-white/5">
                      <div className="flex items-center justify-between mb-5">
                        <div>
                          <div className="text-[9px] font-black text-zinc-500 uppercase tracking-[0.3em] italic">Defects vs Energy</div>
                          <div className="text-[10px] text-zinc-600 uppercase tracking-widest mt-1">Mean surviving defects from ensemble trials</div>
                        </div>
                        <div className="text-[8px] font-mono text-zinc-500 uppercase">{energyTrendData.length} points</div>
                      </div>
                      <div className="h-80">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={energyTrendData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#ffffff08" vertical={false} />
                            <XAxis
                              dataKey="label"
                              stroke="#52525b"
                              fontSize={8}
                              axisLine={false}
                              tickLine={false}
                              tick={{ fill: "#71717a", fontWeight: "bold" }}
                            />
                            <YAxis
                              stroke="#52525b"
                              fontSize={8}
                              axisLine={false}
                              tickLine={false}
                              tick={{ fill: "#71717a" }}
                            />
                            <Tooltip
                              cursor={{ fill: "rgba(255,255,255,0.03)" }}
                              contentStyle={{
                                background: "rgba(12,12,14,0.95)",
                                border: "1px solid rgba(255,255,255,0.1)",
                                borderRadius: "16px",
                                fontSize: "10px",
                                backdropFilter: "blur(10px)",
                              }}
                            />
                            <Bar dataKey="defect_mean" radius={[8, 8, 0, 0]} barSize={28}>
                              {energyTrendData.map((entry: any, index: number) => (
                                <Cell key={index} fill={entry.temperature_K >= 600 ? "#6366f1" : "#06b6d4"} fillOpacity={0.85} />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>

                    <div className="p-6 rounded-[2rem] bg-white/[0.02] border border-white/5">
                      <div className="flex items-center justify-between mb-5">
                        <div>
                          <div className="text-[9px] font-black text-zinc-500 uppercase tracking-[0.3em] italic">Defects vs Temperature</div>
                          <div className="text-[10px] text-zinc-600 uppercase tracking-widest mt-1">Conditioned on the highest PKA energy available</div>
                        </div>
                        <div className="text-[8px] font-mono text-zinc-500 uppercase">{temperatureTrendData.length} points</div>
                      </div>
                      <div className="h-80">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={temperatureTrendData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#ffffff08" vertical={false} />
                            <XAxis
                              dataKey="label"
                              stroke="#52525b"
                              fontSize={8}
                              axisLine={false}
                              tickLine={false}
                              tick={{ fill: "#71717a", fontWeight: "bold" }}
                            />
                            <YAxis
                              stroke="#52525b"
                              fontSize={8}
                              axisLine={false}
                              tickLine={false}
                              tick={{ fill: "#71717a" }}
                            />
                            <Tooltip
                              cursor={{ fill: "rgba(255,255,255,0.03)" }}
                              contentStyle={{
                                background: "rgba(12,12,14,0.95)",
                                border: "1px solid rgba(255,255,255,0.1)",
                                borderRadius: "16px",
                                fontSize: "10px",
                                backdropFilter: "blur(10px)",
                              }}
                            />
                            <Bar dataKey="defect_mean" radius={[8, 8, 0, 0]} barSize={28}>
                              {temperatureTrendData.map((entry: any, index: number) => (
                                <Cell key={index} fill={entry.temperature_K >= 600 ? "#f97316" : "#06b6d4"} fillOpacity={0.85} />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>

                    <div className="xl:col-span-2 p-6 rounded-[2rem] bg-white/[0.02] border border-white/5">
                      <div className="flex items-center justify-between mb-5">
                        <div>
                          <div className="text-[9px] font-black text-zinc-500 uppercase tracking-[0.3em] italic">Trial Spread</div>
                          <div className="text-[10px] text-zinc-600 uppercase tracking-widest mt-1">
                            Individual trial defect counts for {selectedCondition ? `${Math.round(selectedCondition.energy_ev)} eV @ ${Math.round(selectedCondition.temperature_K)}K` : "the selected condition"}
                          </div>
                        </div>
                        <div className="text-[8px] font-mono text-zinc-500 uppercase">{selectedTrialSeries.length} trials</div>
                      </div>
                      <div className="h-72">
                        <ResponsiveContainer width="100%" height="100%">
                          <ScatterChart>
                            <CartesianGrid strokeDasharray="3 3" stroke="#ffffff08" />
                            <XAxis
                              dataKey="trial"
                              name="Trial"
                              stroke="#52525b"
                              fontSize={8}
                              axisLine={false}
                              tickLine={false}
                              tick={{ fill: "#71717a", fontWeight: "bold" }}
                            />
                            <YAxis
                              dataKey="defects"
                              name="Defects"
                              stroke="#52525b"
                              fontSize={8}
                              axisLine={false}
                              tickLine={false}
                              tick={{ fill: "#71717a" }}
                            />
                            {selectedCondition?.mean_defects !== null && selectedCondition?.mean_defects !== undefined && (
                              <ReferenceLine y={selectedCondition.mean_defects} stroke="#a855f7" strokeDasharray="4 4" />
                            )}
                            <Tooltip
                              cursor={{ strokeDasharray: "3 3" }}
                              contentStyle={{
                                background: "rgba(12,12,14,0.95)",
                                border: "1px solid rgba(255,255,255,0.1)",
                                borderRadius: "16px",
                                fontSize: "10px",
                                backdropFilter: "blur(10px)",
                              }}
                            />
                            <Scatter data={selectedTrialSeries} fill="#06b6d4" />
                          </ScatterChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : view === "report" ? (
            <div className="h-full overflow-y-auto px-12 py-16 scroll-smooth custom-scrollbar">
               <div className="max-w-3xl mx-auto prose prose-invert prose-cyan prose-sm lg:prose-base">
                  <ReactMarkdown 
                    components={{
                       h1: ({...props}) => <h1 className="text-white font-black tracking-tight uppercase italic mb-8 border-b border-white/10 pb-4" {...props} />,
                       h2: ({...props}) => <h2 className="text-cyan-400 font-bold tracking-widest uppercase text-sm mt-12 mb-4 flex items-center gap-3" {...props} />,
                       strong: ({...props}) => <strong className="text-white font-bold" {...props} />,
                       p: ({...props}) => <p className="text-zinc-400 leading-relaxed mb-6" {...props} />,
                       li: ({...props}) => <li className="text-zinc-400 mb-2 marker:text-cyan-500" {...props} />,
                    }}
                  >
                    {reportMd?.content || "# Research Unavailable\nThis experiment does not contain a structured research log. Please run a new discovery session."}
                  </ReactMarkdown>
               </div>
            </div>
          ) : view === "data" ? (
            <div className="h-full overflow-y-auto px-12 py-16 custom-scrollbar">
              <div className="max-w-5xl mx-auto">
                <header className="mb-10 flex items-end justify-between border-b border-white/5 pb-6">
                   <div>
                     <h2 className="text-xs font-bold text-cyan-500 uppercase tracking-[0.4em] mb-2">Molecular Census</h2>
                     <p className="text-[10px] text-zinc-500 italic uppercase tracking-wider">Per-Atom Energy Gradient & Topology</p>
                   </div>
                   <div className="flex gap-4">
                      <div className="flex flex-col items-end">
                        <span className="text-[8px] text-zinc-600 uppercase tracking-wider">Total Atoms</span>
                        <span className="text-sm font-mono text-white">{atoms?.positions.length.toLocaleString()}</span>
                      </div>
                      {hasEnergyData && (
                        <div className="flex flex-col items-end">
                          <span className="text-[8px] text-zinc-600 uppercase tracking-wider">Avg Energy</span>
                          <span className="text-sm font-mono text-white">{(atoms?.energies?.reduce((a:any,b:any)=>a+b,0) / (atoms?.energies?.length || 1)).toFixed(3)} eV</span>
                        </div>
                      )}
                   </div>
                </header>

                {!hasEnergyData ? (
                  <div className="py-20 flex flex-col items-center justify-center gap-4 bg-white/[0.02] border border-white/5 rounded-[2rem]">
                    <TableIcon className="w-12 h-12 opacity-10" />
                    <p className="text-[10px] uppercase tracking-widest text-zinc-600 font-bold text-center px-10 leading-loose">
                      Legacy Artifact Detected.<br/>
                      <span className="text-zinc-700 italic">Structural data was captured without per-atom energy metadata.</span>
                    </p>
                  </div>
                ) : (
                  <div className="overflow-x-auto border border-white/5 rounded-2xl bg-black/20">
                    <table className="w-full text-left text-[10px] font-mono border-collapse">
                      <thead className="bg-white/5 text-zinc-500 uppercase tracking-widest">
                        <tr>
                          <th className="px-5 py-4 font-bold border-b border-white/5">Index</th>
                          <th className="px-5 py-4 font-bold border-b border-white/5">Element</th>
                          <th className="px-5 py-4 font-bold border-b border-white/5">Position (X, Y, Z)</th>
                          <th className="px-5 py-4 font-bold border-b border-white/5">Local Energy (eV)</th>
                          <th className="px-5 py-4 font-bold border-b border-white/5 text-right">Defect State</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {atoms?.positions.slice(0, 100).map((pos: any, i: number) => {
                           const initial = atoms?.initial_positions?.[i];
                           const d2 = initial ? Math.pow(pos[0]-initial[0],2)+Math.pow(pos[1]-initial[1],2)+Math.pow(pos[2]-initial[2],2) : 0;
                           const isDefect = d2 > 1.44;
                           return (
                            <tr key={i} className="hover:bg-white/[0.02] transition-colors group">
                              <td className="px-5 py-3 text-zinc-600">#{i.toString().padStart(4, '0')}</td>
                              <td className="px-5 py-3 text-white font-bold">{atoms.numbers[i]}</td>
                              <td className="px-5 py-3 text-zinc-500 opacity-60">[{pos[0].toFixed(2)}, {pos[1].toFixed(2)}, {pos[2].toFixed(2)}]</td>
                              <td className="px-5 py-3">
                                <span className={cn(
                                  "px-2 py-0.5 rounded border",
                                  atoms.energies?.[i] > -4 ? "text-rose-400 border-rose-500/20 bg-rose-500/5" : "text-cyan-400 border-cyan-500/20 bg-cyan-500/5"
                                )}>
                                  {atoms.energies?.[i]?.toFixed(4) || "N/A"}
                                </span>
                              </td>
                              <td className="px-5 py-3 text-right">
                                <span className={cn(
                                  "w-2 h-2 rounded-full inline-block",
                                  isDefect ? "bg-rose-500 shadow-[0_0_8px_#f43f5e]" : "bg-emerald-500 opacity-20"
                                )} />
                              </td>
                            </tr>
                           );
                        })}
                      </tbody>
                    </table>
                    {atoms?.positions.length > 100 && (
                      <div className="p-4 text-center text-[9px] text-zinc-600 italic bg-white/5 border-t border-white/5 uppercase tracking-widest">
                         Showing first 100 of {atoms.positions.length} atoms. Download full manifest for complete analysis.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="h-full overflow-y-auto px-12 py-16 custom-scrollbar">
               <h2 className="text-xs font-bold text-cyan-500 uppercase tracking-[0.4em] mb-12 flex items-center gap-3">
                  <Settings2 className="w-4 h-4" /> Experiment Configuration
               </h2>
               {!spec ? (
                  <div className="py-20 flex flex-col items-center justify-center gap-4 bg-white/[0.02] border border-white/5 rounded-[2rem] max-w-4xl mx-auto">
                    <Box className="w-12 h-12 opacity-10" />
                    <p className="text-[10px] uppercase tracking-widest text-zinc-600 font-bold text-center px-10 leading-loose">
                      Discovery Blueprint Missing.<br/>
                      <span className="text-zinc-700 italic text-[8px]">This session was recorded before DAG Spec persistence was enabled.</span>
                    </p>
                  </div>
               ) : (
                <div className="grid grid-cols-1 gap-6 max-w-4xl mx-auto">
                    {spec.dag.map((node: any) => (
                      <div key={node.id} className="group p-8 rounded-3xl bg-white/[0.02] border border-white/5 transition-all hover:bg-white/[0.04] hover:border-white/10">
                        <div className="flex items-center justify-between border-b border-white/5 pb-4 mb-6">
                            <div className="flex flex-col gap-1">
                                <span className="text-[10px] text-zinc-600 uppercase tracking-widest font-bold">Node Identity</span>
                                <span className="text-white font-mono font-bold text-lg">{node.id}</span>
                            </div>
                            <div className="flex flex-col items-end gap-1">
                                <span className="text-[10px] text-zinc-600 uppercase tracking-widest font-bold">Operation</span>
                                <span className="text-[10px] px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 font-bold uppercase tracking-widest">{node.type}</span>
                            </div>
                        </div>
                        <div className="bg-black/40 rounded-2xl p-6 border border-white/5 group-hover:border-white/10 transition-colors">
                            <pre className="text-[11px] text-zinc-400 font-mono leading-relaxed overflow-x-auto custom-scrollbar">
                                {JSON.stringify(node.params, null, 3)}
                            </pre>
                        </div>
                      </div>
                    ))}
                </div>
               )}
            </div>
          )}
        </div>

        {/* Floating Metrics Overlay (Only in Viz) */}
        {modulusMetrics.length > 0 && view === "viz" && !isLoading && (
          <div className="absolute top-8 left-8 w-[22rem] p-8 rounded-[2.5rem] bg-[#0c0c0e]/80 border border-white/10 shadow-[0_32px_64px_-16px_rgba(0,0,0,0.6)] backdrop-blur-2xl z-30 transition-all hover:border-cyan-500/30 group">
            <div className="flex items-center justify-between mb-8">
               <h2 className="text-[11px] font-black text-white/90 uppercase tracking-[0.3em] italic">Mechanical Comparison</h2>
               <div className="flex gap-1">
                  <div className="w-1.5 h-1.5 rounded-full bg-cyan-500" />
                  <div className="w-1.5 h-1.5 rounded-full bg-indigo-500 opacity-40 group-hover:opacity-100 transition-opacity" />
               </div>
            </div>
            
            <div className="h-44 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={modulusMetrics}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#ffffff05" vertical={false} />
                  <XAxis 
                    dataKey="name" 
                    stroke="#52525b" 
                    fontSize={8} 
                    axisLine={false} 
                    tickLine={false} 
                    tick={{ fill: "#71717a", fontWeight: "bold" }}
                  />
                  <YAxis 
                    stroke="#52525b" 
                    fontSize={8} 
                    axisLine={false} 
                    tickLine={false} 
                    tick={{ fill: "#71717a" }}
                  />
                  <Tooltip 
                    cursor={{ fill: 'rgba(255,255,255,0.03)' }}
                    contentStyle={{ 
                      background: "rgba(12,12,14,0.95)", 
                      border: "1px solid rgba(255,255,255,0.1)", 
                      borderRadius: "16px", 
                      fontSize: "10px",
                      backdropFilter: "blur(10px)",
                      boxShadow: "0 10px 25px -5px rgba(0,0,0,0.3)"
                    }} 
                  />
                  <Bar dataKey="val" radius={[6, 6, 6, 6]} barSize={30}>
                    {modulusMetrics.map((_, index) => (
                      <Cell key={index} fill={index === 0 ? "#06b6d4" : "#6366f1"} fillOpacity={0.8} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            
            <div className="mt-8 flex items-center justify-between px-2">
               <div className="flex flex-col gap-1">
                  <span className="text-[8px] text-zinc-600 uppercase tracking-widest font-black italic">Structural Rigidity</span>
                  <div className="flex items-center gap-2">
                    <span className="text-lg font-mono text-white font-bold">{(modulusMetrics[modulusMetrics.length-1]?.val || 0).toFixed(1)} GPa</span>
                  </div>
               </div>
               {modulusMetrics.length > 1 && (
                 <>
                  <div className="h-8 w-[1px] bg-white/5" />
                  <div className="flex flex-col gap-1 items-end">
                      <span className="text-[8px] text-zinc-600 uppercase tracking-widest font-black italic">Evolution</span>
                      <span className={cn(
                        "text-lg font-mono font-bold italic",
                        modulusMetrics[1].val > modulusMetrics[0].val ? "text-cyan-400" : "text-rose-400"
                      )}>
                        {((modulusMetrics[1].val - modulusMetrics[0].val) / (modulusMetrics[0].val || 1) * 100).toFixed(1)}%
                      </span>
                  </div>
                 </>
               )}
            </div>
          </div>
        )}

        {/* Energy Distribution Overlay (Newly Added Visualization) */}
        {hasEnergyData && energyStats && view === "viz" && !isLoading && (
          <div className="absolute bottom-8 right-8 w-80 p-6 rounded-[2rem] bg-[#0c0c0e]/60 border border-white/5 backdrop-blur-xl z-30 transition-all hover:bg-black/60">
             <div className="flex items-center justify-between mb-4">
                <h2 className="text-[9px] font-black text-zinc-500 uppercase tracking-widest italic">Potential Distribution</h2>
                <span className="text-[8px] font-mono text-cyan-500/40">eV / Atom</span>
             </div>
             <div className="h-32 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={energyStats}>
                    <Bar dataKey="count" fill="#06b6d4" fillOpacity={0.4} radius={[2, 2, 0, 0]} />
                    <Tooltip 
                      cursor={{ fill: 'transparent' }}
                      content={({ active, payload }) => {
                        if (active && payload && payload.length) {
                          return (
                            <div className="bg-black/80 border border-white/10 p-2 rounded-lg text-[8px] text-white">
                              {payload[0].value} atoms at ~{payload[0].payload.name} eV
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                  </BarChart>
                </ResponsiveContainer>
             </div>
          </div>
        )}
      </section>
    </main>
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Suspense fallback={<div className="h-screen w-screen bg-[#050505] flex flex-col items-center justify-center text-cyan-500 font-mono">
        <div className="relative mb-4">
          <Loader2 className="w-10 h-10 animate-spin opacity-20" />
          <Zap className="absolute inset-0 m-auto w-4 h-4 animate-pulse" />
        </div>
        <div className="text-[10px] tracking-[0.5em] animate-pulse uppercase">Initializing Physics Engine...</div>
      </div>}>
        <DashboardContent />
      </Suspense>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
