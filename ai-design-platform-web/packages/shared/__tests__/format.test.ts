import { describe, it, expect } from 'vitest';
import { formatDate, formatCurrency } from '../src/utils/format';

describe('formatDate', () => {
  it('should format Date object to YYYY-MM-DD string', () => {
    const date = new Date('2026-01-15');
    expect(formatDate(date)).toBe('2026-01-15');
  });

  it('should format ISO string input', () => {
    expect(formatDate('2026-06-22')).toBe('2026-06-22');
  });
});

describe('formatCurrency', () => {
  it('should format number to CNY currency string', () => {
    expect(formatCurrency(1234.56)).toBe('¥1,234.56');
  });
});
