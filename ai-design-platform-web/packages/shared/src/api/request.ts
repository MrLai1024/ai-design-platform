import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios';
import { credentials } from '../utils/credentials';
import { GLOBAL_EVENTS } from '../constants/events';

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
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      // Clear credentials and notify the base app (redirect to login handled there)
      credentials.remove();
      localStorage.removeItem('ai_design_token');
      window.dispatchEvent(new CustomEvent(GLOBAL_EVENTS.AUTH_UNAUTHORIZED));
    }
    return Promise.reject(error);
  },
);

/**
 * Typed wrappers around the shared axios instance.
 *
 * The response interceptor above returns `response.data` (the raw response
 * body), so these promises resolve with the body itself — NOT an AxiosResponse
 * and NOT an `ApiResponse` envelope. That contract is encoded here in one
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
