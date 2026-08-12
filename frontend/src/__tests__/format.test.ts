import { describe, it, expect } from 'vitest';
import {
  EM_DASH,
  fmtUsd,
  fmtNum,
  fmtPct,
  fmtRatioPct,
  fmtQty,
  fmtCompact,
  fmtDateTime,
  fmtTime,
  fmtDuration,
  signClass,
} from '../lib/format';

/**
 * These formatters take untrusted network data. A throw here becomes a render
 * throw, and React unmounts the whole tree on a render throw — which is how a
 * single null price used to white-screen the entire terminal. So the contract
 * under test is: never throw, always return a string.
 */

const BAD_INPUTS = [null, undefined, NaN, Infinity, -Infinity, 'abc', {}, []];

describe('format: never throws on bad input', () => {
  const numeric = { fmtUsd, fmtNum, fmtPct, fmtRatioPct, fmtQty, fmtCompact, fmtDuration };

  for (const [name, fn] of Object.entries(numeric)) {
    it(`${name} returns a dash for every non-finite input`, () => {
      for (const bad of BAD_INPUTS) {
        expect(() => fn(bad as never)).not.toThrow();
        expect(fn(bad as never)).toBe(EM_DASH);
      }
    });
  }

  for (const [name, fn] of Object.entries({ fmtDateTime, fmtTime })) {
    it(`${name} returns a dash for invalid dates`, () => {
      for (const bad of [...BAD_INPUTS, '', 'not-a-date']) {
        expect(() => fn(bad as never)).not.toThrow();
        expect(fn(bad as never)).toBe(EM_DASH);
      }
    });
  }

  it('signClass never throws and is neutral for unknown values', () => {
    for (const bad of BAD_INPUTS) {
      expect(() => signClass(bad as never)).not.toThrow();
      expect(signClass(bad as never)).toBe('text-slate-400');
    }
  });
});

describe('format: correct output for valid input', () => {
  it('fmtUsd', () => {
    expect(fmtUsd(1234.5)).toBe('$1,234.50');
    expect(fmtUsd(0)).toBe('$0.00');
    expect(fmtUsd(-42.1)).toBe('-$42.10');
  });

  it('fmtNum honours decimals', () => {
    expect(fmtNum(1.23456, 2)).toBe('1.23');
    expect(fmtNum(5, 0)).toBe('5');
  });

  it('fmtPct signs positive values', () => {
    expect(fmtPct(1.5)).toBe('+1.50%');
    expect(fmtPct(-1.5)).toBe('-1.50%');
    expect(fmtPct(0)).toBe('+0.00%');
  });

  it('fmtRatioPct converts fractions to percent', () => {
    // engine/metrics.py returns fractions (0.05 = 5%) — rendering these with
    // fmtPct instead would show "0.05%" and understate every metric 100x.
    expect(fmtRatioPct(0.05)).toBe('5.0%');
    expect(fmtRatioPct(1)).toBe('100.0%');
  });

  it('fmtQty', () => {
    expect(fmtQty(0.123456789, 4)).toBe('0.1235');
  });

  it('fmtCompact', () => {
    expect(fmtCompact(1500)).toBe('1.5K');
  });

  it('fmtDuration', () => {
    expect(fmtDuration(45)).toBe('45s');
    expect(fmtDuration(90)).toBe('1m 30s');
    expect(fmtDuration(3660)).toBe('1h 01m');
    expect(fmtDuration(0)).toBe('0s');
  });

  it('fmtDuration rejects negatives', () => {
    expect(fmtDuration(-5)).toBe(EM_DASH);
  });

  it('signClass', () => {
    expect(signClass(1)).toBe('text-emerald-400');
    expect(signClass(-1)).toBe('text-rose-400');
    expect(signClass(0)).toBe('text-slate-400');
  });
});
