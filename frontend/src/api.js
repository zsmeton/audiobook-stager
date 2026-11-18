export async function api(path, options = {}) {
  const headers = { Accept: "application/json" };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers: { ...headers, ...options.headers } });
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }
  if (!response.ok) {
    const detail = data && data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail && detail.message) || (data && data.message) || response.statusText || "Request failed";
    const error = new Error(message);
    error.status = response.status;
    error.detail = detail && typeof detail === "object" ? detail : null;
    throw error;
  }
  return data;
}
