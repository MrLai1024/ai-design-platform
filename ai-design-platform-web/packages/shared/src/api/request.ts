import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios';
import { credentials } from '../utils/credentials';
import { GLOBAL_EVENTS } from '../constants/events';

/**
 * 统一响应信封(后端契约):
 * - 成功:{ code: 0, msg: "success", data: <业务数据本体> },无数据接口 data 为 null
 * - 错误:{ code: <业务码>, msg: "<中文提示>", data: null },HTTP 状态码保留
 */
interface ApiEnvelope {
  code: number;
  msg: string;
  data?: unknown;
}

/** 拦截器错误标记:error.message 为服务端 msg,apiCode 为业务码,response 保留 HTTP 状态 */
export interface ApiErrorLike {
  apiCode?: number;
  response?: AxiosResponse;
}

/** 判断响应体是否为统一信封(含数字 code 字段的对象) */
function isEnvelope(body: unknown): body is ApiEnvelope {
  return (
    typeof body === 'object' &&
    body !== null &&
    typeof (body as { code?: unknown }).code === 'number'
  );
}

const instance: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor
instance.interceptors.request.use(
  (config) => {
    // Prefer the token from the credentials store, falling back to the legacy ai_design_token raw key
    const token = credentials.getToken() ?? localStorage.getItem('ai_design_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// Response interceptor
instance.interceptors.response.use(
  (response) => {
    const body = response.data;
    // 统一信封:code === 0 → 解包 data(业务数据本体);code !== 0 → 抛携带 msg 的业务错误
    if (isEnvelope(body)) {
      if (body.code === 0) {
        return body.data;
      }
      const error = new Error(body.msg || '请求失败') as Error & ApiErrorLike;
      error.apiCode = body.code;
      error.response = response;
      return Promise.reject(error);
    }
    // 非信封响应(后端迁移过渡期):原样返回,保持旧行为
    return body;
  },
  (error) => {
    if (error.response?.status === 401) {
      // Clear credentials and notify the base app (redirect to login handled there)
      credentials.remove();
      localStorage.removeItem('ai_design_token');
      window.dispatchEvent(new CustomEvent(GLOBAL_EVENTS.AUTH_UNAUTHORIZED));
    }
    // HTTP 错误 + 信封体:优先携带服务端 msg 与业务码,
    // 保留 error.response 供消费方按 status 鸭子判断(如 409 冲突)
    const body = error.response?.data;
    if (isEnvelope(body)) {
      error.message = body.msg || error.message;
      error.apiCode = body.code;
    }
    return Promise.reject(error);
  },
);

/**
 * Typed wrappers around the shared axios instance.
 *
 * The response interceptor unwraps the `{ code, msg, data }` envelope:
 * - code === 0 → resolve with the business payload (`data`)
 * - code !== 0 or HTTP error → reject with `error.message` = server msg,
 *   `error.apiCode` = business code, `error.response` = original response.
 * So these promises resolve with the business payload itself — NOT an
 * AxiosResponse and NOT the envelope. That contract is encoded here in one
 * place via axios's `R` generic; API modules (user/team/project) rely on it
 * and declare their real return types accordingly.
 */
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  return instance.request<T, T>(config);
}

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return instance.get<T, T>(url, { params });
}

export async function post<T>(url: string, data?: unknown): Promise<T> {
  return instance.post<T, T>(url, data);
}

export const http = instance;
