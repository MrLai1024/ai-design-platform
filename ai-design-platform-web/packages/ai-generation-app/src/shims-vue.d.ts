declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<object, object, unknown>;
  export default component;
}

declare module '@babel/standalone' {
  interface BabelTransformOptions {
    filename?: string
    presets?: Array<string | [string, Record<string, unknown>]>
  }
  export function transform(
    code: string,
    options?: BabelTransformOptions,
  ): { code?: string | null }
}
