import { act, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { ToastProvider, useToast } from './Toasts';

describe('ToastProvider', () => {
  it('hands out the same toast object across re-renders, so pushing a toast does not restart effects that depend on it', async () => {
    const seen: ReturnType<typeof useToast>[] = [];
    function Probe() {
      const toast = useToast();
      const [, rerender] = useState(0);
      seen.push(toast);
      return (
        <button
          onClick={() => {
            toast.push('Hello', 'world');
            rerender((n) => n + 1);
          }}
        >
          push
        </button>
      );
    }
    render(
      <ToastProvider>
        <Probe />
      </ToastProvider>,
    );
    await act(async () => {
      screen.getByRole('button', { name: 'push' }).click();
    });
    expect(await screen.findByText('Hello')).toBeInTheDocument();
    expect(seen.length).toBeGreaterThan(1);
    expect(new Set(seen).size).toBe(1);
  });
});
