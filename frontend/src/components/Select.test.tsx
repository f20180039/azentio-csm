import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { Select } from './Select';

const OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'OPEN', label: 'Open' },
  { value: 'DECIDED', label: 'Decided' },
  { value: 'DRAFT', label: 'Draft' },
];

function Harness({ onChange }: { onChange: (v: string) => void }) {
  const [value, setValue] = useState('');
  return (
    <>
      <label htmlFor="status">Status</label>
      <Select
        id="status"
        value={value}
        options={OPTIONS}
        onChange={(v) => {
          setValue(v);
          onChange(v);
        }}
      />
      <button type="button">Outside</button>
    </>
  );
}

describe('Select', () => {
  it('opens a listbox from its labelled button and marks the selected option', () => {
    render(<Harness onChange={vi.fn()} />);
    const button = screen.getByLabelText('Status');
    expect(button).toHaveAttribute('aria-haspopup', 'listbox');
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'All statuses' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('option', { name: 'Open' })).toHaveAttribute('aria-selected', 'false');
  });

  it('picks with the keyboard, calls onChange and returns focus to the button', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const button = screen.getByLabelText('Status');
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    fireEvent.keyDown(list, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('DECIDED');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(button).toHaveTextContent('Decided');
    expect(button).toHaveFocus();
  });

  it('supports Home, End and type-ahead', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const button = screen.getByLabelText('Status');
    fireEvent.click(button);
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'End' });
    fireEvent.keyDown(list, { key: ' ' });
    expect(onChange).toHaveBeenLastCalledWith('DRAFT');
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Home' });
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'o' });
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith('OPEN');
  });

  it('closes on Escape without changing the value', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const button = screen.getByLabelText('Status');
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'ArrowDown' });
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Escape' });
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(button).toHaveFocus();
  });

  it('closes on a click outside', () => {
    render(<Harness onChange={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('Status'));
    fireEvent.mouseDown(screen.getByRole('button', { name: 'Outside' }));
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('picks an option with the mouse', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByLabelText('Status'));
    fireEvent.click(screen.getByRole('option', { name: 'Open' }));
    expect(onChange).toHaveBeenCalledWith('OPEN');
  });
});
