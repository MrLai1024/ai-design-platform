/// <reference types="vite/client" />

// Vite client types are not available at type-check time because vite is not a
// direct dependency (this project uses webpack for builds). Provide the minimal
// interface needed for import.meta.env.DEV usage.
interface ImportMetaEnv {
  readonly DEV: boolean
  readonly PROD: boolean
  readonly MODE: string
  readonly BASE_URL: string
  [key: string]: unknown
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
