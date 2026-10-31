import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CHANNEL_LABEL } from '../api/support';
import { ToastProvider } from '../components/Toasts';
import { SupportChannel } from '../vocab';
import { SupportCall } from './SupportCall';

const h = vi.hoisted(() => ({
  allowed: { configured: false, numbers: [] as { id: string; masked: string }[] },
  placed: [] as string[],
  getCall: vi.fn(),
}));

vi.mock('../api/phone', async (orig) => ({
  ...(await orig<typeof import('../api/phone')>()),
  getPhoneAllowed: vi.fn(async () => h.allowed),
  placeSupportPhoneCall: vi.fn(async (numberId: string) => {
    h.placed.push(numberId);
    return { call_id: 'phone-call-1', status: 'dialling' };
  }),
}));

vi.mock('../api/support', async (orig) => {
  const real = await orig<typeof import('../api/support')>();
  return { ...real, getCall: h.getCall };
});

function mount() {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={['/support/new']}>
        <Routes>
          <Route path="/support/new" element={<SupportCall />} />
          <Route path="/support/calls/:callId" element={<p>call {window.location.pathname}</p>} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  h.placed = [];
  h.getCall.mockReset();
});

describe('SupportCall: call a phone', () => {
  it('labels the phone channel', () => {
    expect(CHANNEL_LABEL[SupportChannel.PHONE]).toBe('Phone');
  });

  it('is hidden when phone calls are not set up', async () => {
    h.allowed = { configured: false, numbers: [] };
    mount();
    await screen.findByRole('button', { name: 'Start talking' });
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Call a phone' })).not.toBeInTheDocument());
  });

  it('lists the masked numbers and rings the chosen one', async () => {
    h.allowed = {
      configured: true,
      numbers: [
        { id: '0', masked: '+91 ••••• •4417' },
        { id: '1', masked: '+1 ••••• •0123' },
      ],
    };
    mount();
    const select = await screen.findByLabelText('Phone number');
    fireEvent.click(select);
    expect(screen.getByRole('option', { name: '+91 ••••• •4417' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('option', { name: '+1 ••••• •0123' }));
    fireEvent.click(screen.getByRole('button', { name: 'Call a phone' }));
    await waitFor(() => expect(h.placed).toEqual(['1']));
    expect(await screen.findByText('Phone ringing')).toBeInTheDocument();
  });
});
