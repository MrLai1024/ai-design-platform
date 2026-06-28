// Dynamically set webpack publicPath for qiankun.
// Must be imported BEFORE any other module in the entry file.
declare let __webpack_public_path__: string;

if ((window as Record<string, unknown>).__POWERED_BY_QIANKUN__) {
  // eslint-disable-next-line no-global-assign, no-undef
  __webpack_public_path__ = (window as Record<string, unknown>)
    .__INJECTED_PUBLIC_PATH_BY_QIANKUN__ as string;
}
