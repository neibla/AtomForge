export interface ApiError extends Error {
  info?: unknown;
  status?: number;
}

function messageFromBody(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  if (typeof body === "string" && body.trim()) return body.trim();
  return `Request failed (${status})`;
}

export async function fetcher<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(input, init);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (contentType.startsWith("image/") || contentType.includes("octet-stream")) {
    if (!response.ok) {
      const body = await response.text();
      const error: ApiError = new Error(
        messageFromBody(body || undefined, response.status),
      );
      error.status = response.status;
      error.info = body;
      throw error;
    }
    return (await response.blob()) as T;
  }

  const text = [204, 205, 304].includes(response.status)
    ? ""
    : await response.text();
  let body: unknown = text;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // Proxies and development servers may return plain-text failures.
      body = text;
    }
  } else {
    body = {};
  }

  if (!response.ok) {
    const error: ApiError = new Error(messageFromBody(body, response.status));
    error.status = response.status;
    error.info = body;
    throw error;
  }
  return body as T;
}
