import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ErrorBoundary } from '../components/common/ErrorBoundary';

describe('ErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">Hello</div>
      </ErrorBoundary>
    );
    expect(screen.getByTestId('child')).toBeDefined();
    expect(screen.getByText('Hello')).toBeDefined();
  });

  it('renders fallback when child throws', () => {
    const BadComponent = () => {
      throw new Error('Boom');
    };

    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary fallback={<div data-testid="fallback">Custom fallback</div>}>
        <BadComponent />
      </ErrorBoundary>
    );

    expect(screen.getByTestId('fallback')).toBeDefined();
    expect(screen.getByText('Custom fallback')).toBeDefined();
    spy.mockRestore();
  });

  it('renders default error UI when no fallback provided', () => {
    const BadComponent = () => {
      throw new Error('Boom');
    };

    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <BadComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText('Something went wrong')).toBeDefined();
    expect(screen.getByText('Boom')).toBeDefined();
    spy.mockRestore();
  });
});
