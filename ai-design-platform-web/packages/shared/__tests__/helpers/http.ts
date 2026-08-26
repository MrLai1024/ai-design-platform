import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios';

export interface CapturedRequest {
  method: string;
  url: string;
  baseURL?: string;
  data?: unknown;
  params?: unknown;
  headers: Record<string, unknown>;
}

/**
 * Capture-style axios adapter: assign the returned adapter to `http.defaults.adapter`
 * to record method/url/params/data/headers of outgoing requests without real network.
 *
 * @param responseData — the raw HTTP response body to resolve with. The response
 * interceptor returns `response.data`, so API calls resolve with this value directly.
 */
export function installCaptureAdapter(responseData: unknown = {}): {
  calls: CapturedRequest[];
  adapter: AxiosAdapter;
} {
  const calls: CapturedRequest[] = [];
  const adapter: AxiosAdapter = (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    const headers: Record<string, unknown> = {};
    const h = config.headers as unknown as { toJSON?: () => Record<string, unknown> } | null;
    if (h && typeof h.toJSON === 'function') {
      Object.assign(headers, h.toJSON());
    }
    calls.push({
      method: config.method ?? 'get',
      url: config.url ?? '',
      baseURL: config.baseURL,
      data: config.data,
      params: config.params,
      headers,
    });
    return Promise.resolve({
      data: responseData,
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    });
  };
  return { calls, adapter };
}
