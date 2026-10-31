import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

describe('App in mock mode', () => {
  it('signs in to the support desk, lists the queue and opens a case with evidence and a security banner', async () => {
    vi.stubEnv('VITE_MOCK', '1');
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    const { App } = await import('./App');
    render(<App />);

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reviewer' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'reviewer' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { name: 'Customer service desk' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Queue' }));
    expect(await screen.findByText('Review queue')).toBeInTheDocument();
    const row = await screen.findByText('Example: Rohan M. · personal loan ₹6,00,000');
    fireEvent.click(row);

    expect(await screen.findByText('Possible document manipulation')).toBeInTheDocument();
    expect(await screen.findByText('Balance chain breaks after a salary credit')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: /Evidence 1/ })[0]);
    expect(await screen.findAllByText(/ACH CR SALARY NORTHWIND TECH/)).not.toHaveLength(0);
  });
});
