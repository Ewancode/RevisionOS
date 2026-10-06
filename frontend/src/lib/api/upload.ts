import { ApiError, readCookie, toApiError } from "@/lib/api/client";

/** POST a file as the raw request body (how the API takes uploads), with
 * progress. Resolves with the JSON body of a 202 response. */
export function uploadRaw<T>(url: string, file: File, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    const csrf = readCookie("__Host-rev_csrf");
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status === 202) resolve(body as T);
      else reject(toApiError(xhr.status, body));
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "The upload failed. Check your connection."));
    xhr.send(file);
  });
}

/** "4.2 MB" */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}
