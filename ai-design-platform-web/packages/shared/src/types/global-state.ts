/** Global state shape shared across micro-apps via qiankun initGlobalState */
export interface GlobalState {
  /** Current authenticated user info */
  user?: {
    id: string;
    name: string;
    avatar?: string;
  };
  /** Current tenant / workspace info */
  tenant?: {
    id: string;
    name: string;
  };
  /** Cross-app notification event */
  event?: {
    type: string;
    payload?: unknown;
    timestamp: number;
  };
}
