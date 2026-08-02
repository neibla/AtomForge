import { useEffect, useState } from "react";

import { getArtifactBlob } from "@/api";
import { errorMessage } from "@/lib/utils";
import type { ImageVisualization } from "@/types";

interface ImageViewerProps {
  experimentId: string;
  visualization: ImageVisualization;
}

export default function ImageViewer({
  experimentId,
  visualization,
}: ImageViewerProps) {
  const artifactKey = `${experimentId}:${visualization.artifact_path}`;
  const [result, setResult] = useState<{
    key: string;
    url?: string;
    error?: string;
  }>({ key: "" });

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    void getArtifactBlob(experimentId, visualization.artifact_path)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (active) setResult({ key: artifactKey, url: objectUrl });
      })
      .catch((reason: unknown) => {
        if (active) {
          setResult({
            key: artifactKey,
            error: errorMessage(reason, "Image artifact unavailable"),
          });
        }
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifactKey, experimentId, visualization.artifact_path]);

  const current = result.key === artifactKey ? result : null;

  return (
    <div className="flex h-full flex-col bg-slate-50 p-5 lg:p-8">
      <p className="text-sm font-medium text-indigo-700">Image</p>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">
        {visualization.title}
      </h3>
      <div className="mt-5 flex min-h-0 flex-1 items-center justify-center overflow-auto rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        {current?.error ? (
          <p className="text-sm text-rose-700">{current.error}</p>
        ) : null}
        {!current ? (
          <p className="text-sm text-slate-500">Loading image artifact…</p>
        ) : null}
        {current?.url ? (
          <img
            src={current.url}
            alt={visualization.alt}
            className="max-h-full max-w-full object-contain"
          />
        ) : null}
      </div>
    </div>
  );
}
