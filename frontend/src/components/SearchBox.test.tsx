import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { matches } from '../search';
import { SearchBox, useUrlQuery } from './SearchBox';

const FRUIT = ['Apple', 'Apricot', 'Banana', 'Cherry'];

function Harness() {
  const [q, setQ] = useUrlQuery();
  const shown = FRUIT.filter((f) => matches(q, f));
  const loc = useLocation();
  return (
    <>
      <SearchBox value={q} onChange={setQ} label="Search fruit" placeholder="Search fruit by name" shown={shown.length} total={FRUIT.length} />
      <input aria-label="Other field" />
      <ul>
        {shown.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>
      <output data-testid="search">{loc.search}</output>
    </>
  );
}

const mount = (path = '/?status=OPEN') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Harness />
    </MemoryRouter>,
  );

describe('SearchBox', () => {
  it('filters after typing, shows the count, and keeps other URL params', async () => {
    mount();
    const box = screen.getByRole('searchbox', { name: 'Search fruit' });
    expect(box).toHaveAttribute('placeholder', 'Search fruit by name');
    fireEvent.change(box, { target: { value: 'ap' } });
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2));
    expect(screen.getByText('2 of 4')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByTestId('search')).toHaveTextContent('status=OPEN&q=ap');
  });

  it('reads the query from the URL on load', () => {
    mount('/?q=cherry');
    expect(screen.getByRole('searchbox')).toHaveValue('cherry');
    expect(screen.getAllByRole('listitem').map((l) => l.textContent)).toEqual(['Cherry']);
  });

  it('Escape clears the box and blurs it', async () => {
    mount('/?q=ban');
    const box = screen.getByRole('searchbox');
    box.focus();
    fireEvent.keyDown(box, { key: 'Escape' });
    expect(box).toHaveValue('');
    expect(box).not.toHaveFocus();
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(4));
    expect(screen.getByTestId('search')).not.toHaveTextContent('q=');
  });

  it('the clear button empties the query', async () => {
    mount('/?q=ban');
    fireEvent.click(screen.getByRole('button', { name: 'Clear search text' }));
    expect(screen.getByRole('searchbox')).toHaveValue('');
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(4));
  });

  it('"/" focuses the box, but not while typing in another field', () => {
    mount();
    const box = screen.getByRole('searchbox');
    act(() => {
      fireEvent.keyDown(document.body, { key: '/' });
    });
    expect(box).toHaveFocus();

    const other = screen.getByRole('textbox', { name: 'Other field' });
    other.focus();
    fireEvent.keyDown(other, { key: '/' });
    expect(other).toHaveFocus();
  });
});
