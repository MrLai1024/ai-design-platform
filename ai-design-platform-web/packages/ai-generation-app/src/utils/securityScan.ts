// src/utils/securityScan.ts

const DANGEROUS_PATTERNS: Array<[RegExp, string]> = [
  [/document\s*\.\s*cookie/, 'document.cookie'],
  [/document\s*\.\s*domain/, 'document.domain'],
  [/document\s*\.\s*write/, 'document.write'],
  [/\blocalStorage\b/, 'localStorage'],
  [/\bsessionStorage\b/, 'sessionStorage'],
  [/eval\s*\(/, 'eval()'],
  [/new\s+Function\s*\(/, 'new Function()'],
  [/\bwindow\s*\.\s*top\b/, 'window.top'],
  [/\bwindow\s*\.\s*parent\b/, 'window.parent'],
  [/\bwindow\s*\.\s*opener\b/, 'window.opener'],
  [/__proto__/, '__proto__'],
  [/constructor\s*\[/, 'constructor[]'],
  [/import\s*\(/, 'import()'],
  [/fetch\s*\(\s*['"]https?:\/\//, 'fetch() to external URL'],
  [/XMLHttpRequest/, 'XMLHttpRequest'],
]

/**
 * 扫描编译产物中的危险调用，返回第一个匹配的警告信息；
 * 无危险调用时返回 null。
 */
export function scanCode(code: string): string | null {
  for (const [pattern, label] of DANGEROUS_PATTERNS) {
    if (pattern.test(code)) {
      return `代码包含不安全调用: ${label}`
    }
  }
  return null
}
