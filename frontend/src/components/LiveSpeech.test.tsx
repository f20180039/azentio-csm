import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SpeakingBubble, speechStatus } from './LiveSpeech';

describe('live speech', () => {
  it('renders a speaking bubble on the speaker side', () => {
    render(<ol><SpeakingBubble who="agent" /></ol>);
    const bubble = screen.getByLabelText('Agent is speaking');
    expect(bubble).toHaveClass('sc-turn', 'agent', 'sc-speaking');
  });

  it('describes who is talking', () => {
    expect(speechStatus(false, { customer: false, agent: false })).toBe('Microphone off');
    expect(speechStatus(true, { customer: false, agent: false })).toBe('Listening…');
    expect(speechStatus(true, { customer: true, agent: false })).toBe('You’re speaking');
    expect(speechStatus(true, { customer: false, agent: true })).toBe('Agent speaking');
    expect(speechStatus(true, { customer: true, agent: false }, true)).toBe('Paused: the agent isn’t listening');
    expect(speechStatus(false, { customer: false, agent: false }, true)).toBe('Microphone off');
  });
});
