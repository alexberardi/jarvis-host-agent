// wakelive is the always-on loop: ALSA capture (purego) at 48 kHz → streaming decimate to
// 16 kHz → oww → report fires. It measures what the idle node costs.
//
//	wakelive -ort libonnxruntime.so -models DIR -dev dsnoopmic -secs 60 [-threshold 0.4]
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/alsa"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/dsp"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/meter"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/ort"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/oww"
)

func main() {
	lib := flag.String("ort", "libonnxruntime.so", "")
	dir := flag.String("models", ".", "")
	dev := flag.String("dev", "dsnoopmic", "")
	rate := flag.Int("rate", 48000, "")
	secs := flag.Float64("secs", 60, "")
	thr := flag.Float64("threshold", 0.4, "")
	flag.Parse()
	rt, err := ort.Load(*lib)
	must(err)
	d, err := oww.New(rt, *dir, "hey_jarvis_v0.1.onnx", ort.Options{Threads: 1})
	must(err)
	p, err := alsa.Open(*dev, alsa.StreamCapture, *rate, 1, 80000)
	must(err)
	defer p.Close()
	dec := dsp.NewDecimator(*rate / 16000)
	in := make([]int16, *rate*80/1000)
	var pend []int16
	var fires []map[string]any
	var maxScore float32
	lastFire := time.Time{}
	start := time.Now()
	c0 := meter.CPU()
	var late int
	for time.Since(start) < time.Duration(*secs*float64(time.Second)) {
		must(p.Read(in))
		pend = dec.Process(in, pend)
		for len(pend) >= oww.Chunk {
			t := time.Now()
			s, err := d.Process(pend[:oww.Chunk])
			must(err)
			if time.Since(t) > 80*time.Millisecond {
				late++
			}
			pend = append(pend[:0], pend[oww.Chunk:]...)
			maxScore = max(maxScore, s)
			if float64(s) > *thr && time.Since(lastFire) > 8*time.Second { // the node's 8 s debounce
				lastFire = time.Now()
				fires = append(fires, map[string]any{"t_s": time.Since(start).Seconds(), "score": s})
				fmt.Fprintf(os.Stderr, "WAKE t=%.2fs score=%.3f\n", time.Since(start).Seconds(), s)
				d.Reset() // the node resets oww after a fire
			}
		}
	}
	wall := time.Since(start)
	out := map[string]any{"wall_s": wall.Seconds(), "cpu_pct_one_core": 100 * (meter.CPU() - c0).Seconds() / wall.Seconds(),
		"fires": fires, "max_score": maxScore, "xruns": p.Xruns, "chunks_over_80ms": late, "mem": meter.ReadMem().String()}
	b, _ := json.Marshal(out)
	fmt.Println(string(b))
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
