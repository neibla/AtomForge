import { ArrowRight, GitBranch, X } from "lucide-react";

interface ExperimentCreationChooserProps {
  onClose: () => void;
  onChooseDAG: () => void;
}

export function ExperimentCreationChooser({
  onClose,
  onChooseDAG,
}: ExperimentCreationChooserProps) {
  return (
    <div className="app-shell fixed inset-0 z-[60] flex items-center justify-center bg-[#0b141a]/90 p-4 backdrop-blur-sm">
      <section className="w-full max-w-3xl overflow-hidden rounded-2xl border border-[#30464f] bg-[#101d24] shadow-2xl">
        <header className="flex items-start justify-between border-b border-[#30464f] px-6 py-6 lg:px-8">
          <div>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-[#d5794f]">
              Create experiment
            </p>
            <h2 className="font-editorial mt-2 text-2xl font-semibold text-[#f2f7f4]">
              How would you like to start?
            </h2>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-[#a7b4b3]">
              Build the workflow yourself, then inspect its persisted evidence
              and report.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close create experiment dialog"
            onClick={onClose}
            className="rounded-lg p-2 text-[#a7b4b3] transition hover:bg-[#243740] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="p-6 lg:p-8">
          <button
            type="button"
            onClick={onChooseDAG}
            className="group rounded-xl border border-[#466372] bg-[#13262f] p-5 text-left transition hover:border-[#d5794f] hover:bg-[#19313b] focus-visible:outline-2 focus-visible:outline-[#d5794f]"
          >
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#243b44] text-[#a9cbd5]">
              <GitBranch className="h-5 w-5" />
            </span>
            <span className="mt-5 block text-base font-semibold text-[#f2f7f4]">
              Build in the DAG editor
            </span>
            <span className="mt-2 block text-sm leading-relaxed text-[#a7b4b3]">
              Add nodes, connect dependencies, edit parameters, and declare
              acceptance checks yourself.
            </span>
            <span className="mt-6 flex items-center gap-2 text-xs font-semibold text-[#f0a47a]">
              Open DAG editor{" "}
              <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
            </span>
          </button>
        </div>
      </section>
    </div>
  );
}
