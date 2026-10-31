import { render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { AudioOrbs } from './AudioOrbs';

describe('AudioOrbs', () => {
  it('shows both speakers and a listening status while live, without audio APIs', () => {
    render(<AudioOrbs live agentAudio={createRef<HTMLAudioElement>()} />);
    expect(screen.getByText('You')).toBeInTheDocument();
    expect(screen.getByText('Agent')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Listening…');
  });

  it('says the microphone is off when the call is not live', () => {
    render(<AudioOrbs live={false} agentAudio={createRef<HTMLAudioElement>()} />);
    expect(screen.getByRole('status')).toHaveTextContent('Microphone off');
  });
});
