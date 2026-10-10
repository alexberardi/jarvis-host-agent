# The Python node's per-chunk wake work, live: PyAudio 48 kHz mono 3840-sample chunks from
# dsnoopmic → scipy resample_poly(1,3) → clip → oww.predict. usage: pywakelive.py SECS [--lean]
import sys, time, json, types
if "--lean" in sys.argv:
    sys.modules["openwakeword.custom_verifier_model"] = types.SimpleNamespace(train_custom_verifier=None)
import numpy as np, pyaudio, os
if "--noscipy" in sys.argv:
    # Proposed node fix: numpy FIR with resample_poly's filter (61-tap Kaiser beta 5, cutoff 1/3).
    _t = np.arange(-30, 31); _h = np.sinc(_t / 3) * np.kaiser(61, 5.0); _h = (_h / _h.sum()).astype(np.float32)
    def resample_poly(x, up, down):
        return np.convolve(x.astype(np.float32), _h, mode="same")[::down]
else:
    from scipy.signal import resample_poly
from openwakeword.model import Model
import openwakeword
oww = Model(wakeword_models=[os.path.join(os.path.dirname(openwakeword.__file__), "resources/models/hey_jarvis_v0.1.onnx")], inference_framework="onnx")
pa = pyaudio.PyAudio()
idx = next(i for i in range(pa.get_device_count()) if "dsnoopmic" in pa.get_device_info_by_index(i)["name"])
st = pa.open(format=pyaudio.paInt16, channels=1, rate=48000, input=True, input_device_index=idx, frames_per_buffer=3840)
secs = float(sys.argv[1]); t0 = time.time(); c0 = time.process_time(); mx = 0.0
while time.time() - t0 < secs:
    x = np.frombuffer(st.read(3840, exception_on_overflow=False), dtype=np.int16)
    y = np.clip(resample_poly(x, up=1, down=3), -32768, 32767).astype(np.int16)
    mx = max(mx, float(oww.predict(y)["hey_jarvis_v0.1"]))
wall = time.time() - t0
d = {}
for l in open("/proc/self/smaps_rollup"):
    k = l.split(":")[0]
    if k in ("Rss", "Private_Clean", "Private_Dirty"): d[k] = int(l.split()[1]) / 1024
print(json.dumps({"scipy_loaded": "scipy" in sys.modules, "sklearn_loaded": "sklearn" in sys.modules, "cpu_pct_one_core": round(100 * (time.process_time() - c0) / wall, 2), "max_score": mx,
                  "rss_mb": round(d["Rss"], 1), "uss_mb": round(d["Private_Clean"] + d["Private_Dirty"], 1)}))
