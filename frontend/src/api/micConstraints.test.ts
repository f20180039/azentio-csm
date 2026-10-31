import { describe, expect, it, vi } from 'vitest';
import { cleanMicrophone, MIC_CONSTRAINTS } from './support';

describe('cleanMicrophone', () => {
  it('asks the browser for noise suppression, echo cancellation and gain control', async () => {
    const applyConstraints = vi.fn().mockResolvedValue(undefined);
    await cleanMicrophone({ applyConstraints } as unknown as MediaStreamTrack);
    expect(applyConstraints).toHaveBeenCalledWith(MIC_CONSTRAINTS);
    expect(MIC_CONSTRAINTS).toEqual({ noiseSuppression: true, echoCancellation: true, autoGainControl: true });
  });

  it('keeps the raw microphone when the browser refuses', async () => {
    const applyConstraints = vi.fn().mockRejectedValue(new Error('OverconstrainedError'));
    await expect(cleanMicrophone({ applyConstraints } as unknown as MediaStreamTrack)).resolves.toBeUndefined();
  });
});
