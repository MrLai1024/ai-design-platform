import { describe, it, expect } from 'vitest';
import { formatDate } from '../src/utils/format';

describe('formatDate', () => {
  it('should format Date object to YYYY-MM-DD string', () => {
    const date = new Date('2026-01-15');
    expect(formatDate(date)).toBe('2026-01-15');
  });

  it('should format ISO string input', () => {
    expect(formatDate('2026-06-22')).toBe('2026-06-22');
  });
});