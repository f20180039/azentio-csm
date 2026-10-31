import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { setFetcher } from '../api/client';
import { ToastProvider } from '../components/Toasts';
import { Renewals } from './Renewals';

afterEach(() => setFetcher((...args) => fetch(...args)));

describe('Renewals queue', () => {
  it('shows an error with Retry when the fetch fails, not an empty queue', async () => {
    let ok = false;
    setFetcher(async () =>
      ok
        ? new Response('[]', { status: 200 })
        : new Response(JSON.stringify({ title: 'Server error', detail: 'db down' }), { status: 500 }),
    );
    render(
      <ToastProvider>
        <MemoryRouter>
          <Renewals />
        </MemoryRouter>
      </ToastProvider>,
    );
    expect(await screen.findByText('The renewals queue could not be loaded')).toBeInTheDocument();
    expect(screen.queryByText('No renewals due')).not.toBeInTheDocument();
    ok = true;
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No renewals due')).toBeInTheDocument();
  });
});
