# Build the shared 16 kHz test set. Both the Go and Python harnesses read these exact files.
import wave, numpy as np, sys, os
from scipy.signal import resample_poly
from math import gcd
def load(p):
    w = wave.open(p); sr = w.getframerate(); ch = w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64)
    if ch > 1: x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        g = gcd(16000, sr); x = resample_poly(x, 16000 // g, sr // g)
    return np.clip(x, -32768, 32767).astype(np.int16)
rng = np.random.default_rng(1234)
def noise(sec): return (rng.normal(0, 30, int(sec * 16000))).astype(np.int16)
def save(p, x):
    w = wave.open(p, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(x.tobytes()); w.close()
src = sys.argv[1]; out = sys.argv[2]; os.makedirs(out, exist_ok=True)
sets = {"pos_tts": "HeyJarvis.wav", "neg_tts": "Tellmeajoke.wav", "pos_mic": "wake.wav", "pos_mic_cmd": "speaker.wav", "neg_room2": "rec2_16k.wav", "neg_room3": "rec3_16k.wav"}
allx = []
for name, f in sets.items():
    x = np.concatenate([noise(2.0), load(os.path.join(src, f)), noise(1.0)])
    save(os.path.join(out, name + ".wav"), x); allx.append(x)
    print(name, len(x) / 16000)
# A 60 s soak file for CPU-per-realtime-second measurements.
soak = np.concatenate(allx); reps = int(np.ceil(60 * 16000 / len(soak)))
save(os.path.join(out, "soak60.wav"), np.tile(soak, reps)[:60 * 16000]); print("soak60", 60)
