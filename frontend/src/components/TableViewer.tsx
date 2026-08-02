import type { TableVisualization } from "@/types";
import { cn } from "@/lib/utils";

function formatCell(value: unknown): string {
  if (typeof value === "number") {
    return value.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }
  return String(value ?? "—").replaceAll("_", " ");
}

export default function TableViewer({
  visualization,
}: {
  visualization: TableVisualization;
}) {
  return (
    <div className="h-full overflow-auto bg-[#0b141a] p-4 lg:p-6">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#d88a52]">
        Scientific evidence
      </p>
      <h3 className="mt-1 text-lg font-semibold text-[#f0f5f2]">
        {visualization.title}
      </h3>
      {visualization.description ? (
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[#9fb2b9]">
          {visualization.description}
        </p>
      ) : null}
      <div
        className="mt-5 overflow-x-auto rounded-lg border border-[#35515e] bg-[#0e1920] shadow-[0_20px_60px_rgba(0,0,0,0.22)]"
        role="region"
        aria-label={`${visualization.title} table`}
        tabIndex={0}
      >
        <table className="w-full min-w-[58rem] table-fixed border-collapse text-left font-mono text-[0.7rem] leading-relaxed">
          <thead className="bg-[#15262e] text-[#c4d2d5]">
            <tr>
              {visualization.columns.map((column, columnIndex) => (
                <th
                  key={column.field}
                  className={cn(
                    "sticky top-0 z-[1] whitespace-normal px-3 py-2.5 font-semibold lg:px-3.5",
                    columnIndex === 0 && "left-0 z-[2] bg-[#15262e]",
                  )}
                >
                  {column.label}
                  {column.unit ? ` (${column.unit})` : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visualization.rows.map((row, index) => (
              <tr
                key={index}
                className="border-t border-[#2b4550] text-[#dce7e4] even:bg-[#101d24] hover:bg-[#162a33]"
              >
                {visualization.columns.map((column, columnIndex) => (
                  <td
                    key={column.field}
                    className={cn(
                      "whitespace-normal px-3 py-3 align-top lg:px-3.5",
                      columnIndex === 0 &&
                        "sticky left-0 z-[1] bg-[#0e1920] font-semibold",
                      columnIndex === 0 && index % 2 === 1 && "bg-[#101d24]",
                    )}
                  >
                    {formatCell(row[column.field])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
