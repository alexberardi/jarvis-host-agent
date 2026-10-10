# Reference: openwakeword 0.6.0 (onnx) exactly as the node builds it, fed 1280-sample chunks.
# usage: owwref.py [--lean] scores|soak FILE...
import sys, time, json, os, resource
lean = "--lean" in sys.argv
args = [a for a in sys.argv[1:] if a != "--lean"]
def mem():
    d = {}
    for l in open("/proc/self/smaps_rollup"):
        k, v = l.split(":")[0], l.split()[1:2]
        if k in ("Rss", "Private_Clean", "Private_Dirty"): d[k] = int(v[0]) / 1024
    return {"rss_mb": round(d["Rss"], 1), "uss_mb": round(d["Private_Clean"] + d["Private_Dirty"], 1)}
m0 = mem()
if lean:
    # The proposed Python fix: never import the training-only verifier module (sklearn+scipy).
    import types
    sys.modules["openwakeword.custom_verifier_model"] = types.SimpleNamespace(train_custom_verifier=None)
t = time.time()
import numpy as np, wave
from openwakeword.model import Model
t_imp = time.time() - t
m1 = mem()
mods = sorted({k.split(".")[0] for k in sys.modules})
model_path = os.path.join(os.path.dirname(__import__("openwakeword").__file__), "resources/models/hey_jarvis_v0.1.onnx")
oww = Model(wakeword_models=[model_path], inference_framework="onnx")
m2 = mem()
def read(p):
    w = wave.open(p); return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
mode, files = args[0], args[1:]
out = {"import_s": round(t_imp, 2), "mem_start": m0, "mem_after_import": m1, "mem_after_model": m2,
       "scipy_loaded": "scipy" in mods, "sklearn_loaded": "sklearn" in mods}
if mode == "scores":
    res = {}
    for f in files:
        oww.reset()
        for k in oww.prediction_buffer: oww.prediction_buffer[k].clear()
        x = read(f); sc = []
        for i in range(0, len(x) - 1279, 1280):
            sc.append(float(oww.predict(x[i:i+1280])["hey_jarvis_v0.1"]))
        res[os.path.basename(f)] = sc
    out["scores"] = res
else:
    x = read(files[0]); n = len(x) // 1280
    c0 = time.process_time(); w0 = time.time()
    for i in range(n): oww.predict(x[i*1280:(i+1)*1280])
    cpu = time.process_time() - c0; wall = time.time() - w0
    audio_s = n * 1280 / 16000
    out.update({"audio_s": audio_s, "cpu_s": round(cpu, 3), "wall_s": round(wall, 3),
                "cpu_pct_of_one_core_realtime": round(100 * cpu / audio_s, 2), "mem_after_soak": mem()})
print(json.dumps(out))
