// owwbench runs the Go openWakeWord pipeline over 16 kHz WAVs.
//
//	owwbench -ort libonnxruntime.so -models DIR scores a.wav b.wav   → JSON per-frame scores
//	owwbench -ort ... -models DIR soak soak60.wav                    → CPU per realtime second, RSS
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/meter"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/ort"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/oww"
)

func main() {
	lib := flag.String("ort", "libonnxruntime.so", "path to libonnxruntime")
	dir := flag.String("models", ".", "dir with melspectrogram.onnx, embedding_model.onnx and the wake model")
	wake := flag.String("wake", "hey_jarvis_v0.1.onnx", "wake model file")
	noArena := flag.Bool("no-arena", false, "disable the ORT CPU arena")
	flag.Parse()
	out := map[string]any{"mem_start": meter.ReadMem().String()}
	rt, err := ort.Load(*lib)
	must(err)
	out["ort_version"] = rt.Version
	out["mem_after_ort"] = meter.ReadMem().String()
	d, err := oww.New(rt, *dir, *wake, ort.Options{Threads: 1, NoArena: *noArena})
	must(err)
	out["mem_after_models"] = meter.ReadMem().String()
	mode, files := flag.Arg(0), flag.Args()[1:]
	switch mode {
	case "scores":
		res := map[string][]float32{}
		for _, f := range files {
			s, rate, ch, err := meter.ReadWAV(f)
			must(err)
			if rate != 16000 || ch != 1 {
				must(fmt.Errorf("%s: need 16 kHz mono", f))
			}
			d.Reset()
			var sc []float32
			for i := 0; i+oww.Chunk <= len(s); i += oww.Chunk {
				v, err := d.Process(s[i : i+oww.Chunk])
				must(err)
				sc = append(sc, v)
			}
			res[pathBase(f)] = sc
		}
		out["scores"] = res
	case "soak":
		s, _, _, err := meter.ReadWAV(files[0])
		must(err)
		n := len(s) / oww.Chunk
		c0, w0 := meter.CPU(), time.Now()
		var worst time.Duration
		for i := 0; i < n; i++ {
			t := time.Now()
			_, err := d.Process(s[i*oww.Chunk : (i+1)*oww.Chunk])
			must(err)
			worst = max(worst, time.Since(t))
		}
		cpu, wall := meter.CPU()-c0, time.Since(w0)
		audio := float64(n*oww.Chunk) / 16000
		out["audio_s"] = audio
		out["cpu_s"] = cpu.Seconds()
		out["wall_s"] = wall.Seconds()
		out["cpu_pct_of_one_core_realtime"] = 100 * cpu.Seconds() / audio
		out["per_chunk_avg_ms"] = float64(wall.Microseconds()) / 1000 / float64(n)
		out["per_chunk_worst_ms"] = float64(worst.Microseconds()) / 1000
		out["mem_after_soak"] = meter.ReadMem().String()
		out["stage_ms_per_chunk"] = map[string]float64{"mel": ms(d.TMel, n), "embedding": ms(d.TEmb, n), "wake": ms(d.TWake, n)}
	default:
		must(fmt.Errorf("mode: scores|soak"))
	}
	b, _ := json.Marshal(out)
	fmt.Println(string(b))
}

func ms(d time.Duration, n int) float64 { return float64(d.Microseconds()) / 1000 / float64(n) }

func pathBase(p string) string {
	for i := len(p) - 1; i >= 0; i-- {
		if p[i] == '/' {
			return p[i+1:]
		}
	}
	return p
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
