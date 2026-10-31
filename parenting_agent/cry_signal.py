"""Plain signal processing that hears an infant cry, no learned model (Oct 31 2026).

An infant cry is loud, voiced for long stretches, and its pitch sits high, roughly 250 to 600 Hz, where an adult's
speaking voice rarely stays. For a 2 s window at 16 kHz, cut into 50 ms frames, a frame is voiced when it is above
-50 dBFS and its autocorrelation has a peak of at least VOICED_R at a lag inside that band. The window's numbers:

  level_dbfs     loudness of the whole window
  voiced_share   share of frames voiced inside the cry band
  longest_s      longest run of voiced frames, in seconds
  harmonicity    median autocorrelation peak of the voiced frames, 1 is a pure periodic sound
  pitch_hz       median pitch of the voiced frames

A cry is heard when all four limits in the thresholds pass. The limits were chosen on the tune set only
(results/sounds/meta-hearing/tune.json). Pure numpy, runs in the agent's own process.
"""
import numpy as np

RATE = 16000
FRAME = 800
LOW_HZ, HIGH_HZ = 250, 600
FLOOR_DBFS = -50
VOICED_R = 0.45
FEATURES = ("level_dbfs", "voiced_share", "longest_s", "harmonicity")


def frames(x):
    n = x.size // FRAME
    return x[:n * FRAME].reshape(n, FRAME) if n else np.zeros((0, FRAME), np.float32)


def features(samples):
    x = np.asarray(samples, np.float32)
    rms = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    out = {"level_dbfs": round(20 * float(np.log10(max(rms, 1e-9))), 2)}
    f = frames(x)
    if not len(f):
        return {**out, "voiced_share": 0.0, "longest_s": 0.0, "harmonicity": 0.0, "pitch_hz": None}
    f = f - f.mean(axis=1, keepdims=True)
    loud = np.sqrt(np.mean(f ** 2, axis=1)) >= 10 ** (FLOOR_DBFS / 20)
    spectrum = np.fft.rfft(f, 2 * FRAME, axis=1)
    corr = np.fft.irfft(np.abs(spectrum) ** 2, axis=1)[:, :FRAME]
    lo, hi = RATE // HIGH_HZ, RATE // LOW_HZ
    lag = lo + np.argmax(corr[:, lo:hi + 1], axis=1)
    peak = corr[np.arange(len(f)), lag] / np.maximum(corr[:, 0], 1e-12)
    voiced = loud & (peak >= VOICED_R)
    longest = run = 0
    for v in voiced:
        run = run + 1 if v else 0
        longest = max(longest, run)
    return {**out, "voiced_share": round(float(voiced.mean()), 3), "longest_s": round(longest * FRAME / RATE, 3),
            "harmonicity": round(float(np.median(peak[voiced])), 3) if voiced.any() else 0.0,
            "pitch_hz": round(float(np.median(RATE / lag[voiced]))) if voiced.any() else None}


def is_cry(feats, limits):
    return all(feats[name] >= limits[name] for name in FEATURES)
