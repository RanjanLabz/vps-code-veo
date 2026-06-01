const DEFAULT_ORCHESTRATOR_URL = "https://flowkit-global-orchestrator.onrender.com";

export async function onRequest(context) {
  const { request, env, params } = context;
  const baseUrl = env.ORCHESTRATOR_API_URL || DEFAULT_ORCHESTRATOR_URL;
  const requestUrl = new URL(request.url);
  const pathParam = params.path;
  const path = Array.isArray(pathParam) ? pathParam.join("/") : pathParam || "";
  const upstream = new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  upstream.search = requestUrl.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);
  if (env.ORCHESTRATOR_API_KEY) headers.set("x-api-key", env.ORCHESTRATOR_API_KEY);

  return fetch(upstream.toString(), {
    method: request.method,
    headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
  });
}
