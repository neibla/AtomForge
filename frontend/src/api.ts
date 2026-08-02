import { getVisualizationArtifact } from "@/api/default/default";

export async function getArtifactBlob(
  experimentId: string,
  artifactPath: string,
): Promise<Blob> {
  return getVisualizationArtifact(
    encodeURIComponent(experimentId),
    encodePath(artifactPath),
  );
}

function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}
