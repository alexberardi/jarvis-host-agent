// vadbench runs silero VAD (the v4-style model bundled with openwakeword: input, sr, h, c)
// through the same purego ORT binding, 30 ms frames at 16 kHz, and reports CPU per realtime
// second plus the speech fraction per file. The node endpoints on RMS today; this prices the
// upgrade.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/meter"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/ort"
)

func main() {
	lib := flag.String("ort", "libonnxruntime.so", "")
	model := flag.String("model", "silero_vad.onnx", "")
	frame := flag.Int("frame", 480, "samples per frame")
	flag.Parse()
	rt, err := ort.Load(*lib)
	must(err)
	s, err := rt.NewSession(*model, []string{"input", "sr", "h", "c"}, []string{"output", "hn", "cn"}, ort.Options{Threads: 1})
	must(err)
	res := map[string]any{"mem_after_load": meter.ReadMem().String()}
	var totalAudio float64
	c0 := meter.CPU()
	for _, f := range flag.Args() {
		x, _, _, err := meter.ReadWAV(f)
		must(err)
		h, c := make([]float32, 128), make([]float32, 128)
		speech, n := 0, 0
		in := make([]float32, *frame)
		for i := 0; i+*frame <= len(x); i += *frame {
			for j := range in {
				in[j] = float32(x[i+j]) / 32768
			}
			out, err := s.Run(
				ort.Tensor{Shape: []int64{1, int64(*frame)}, F32: in},
				ort.Tensor{I64: []int64{16000}},
				ort.Tensor{Shape: []int64{2, 1, 64}, F32: h},
				ort.Tensor{Shape: []int64{2, 1, 64}, F32: c})
			must(err)
			h, c = out[1].Data, out[2].Data
			if out[0].Data[0] > 0.5 {
				speech++
			}
			n++
		}
		totalAudio += float64(len(x)) / 16000
		res[f] = fmt.Sprintf("speech %d/%d frames", speech, n)
	}
	cpu := meter.CPU() - c0
	res["cpu_pct_of_one_core_realtime"] = 100 * cpu.Seconds() / totalAudio
	res["mem"] = meter.ReadMem().String()
	_ = time.Now
	b, _ := json.Marshal(res)
	fmt.Println(string(b))
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
