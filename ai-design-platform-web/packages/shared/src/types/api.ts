/** Standard API response envelope */
export interface ApiResponse<T = unknown> {
  code: number;
  data: T;
  message: string;
}

/** Paginated list response */
export interface PaginatedResponse<T> {
  list: T[];
  total: number;
  page: number;
  pageSize: number;
}

/** API error shape */
export interface ApiError {
  code: number;
  message: string;
  details?: unknown;
}
