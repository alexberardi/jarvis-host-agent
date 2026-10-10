// audiospike measures audio I/O options on the Pi:
//
//	audiospike capture      -dev dsnoopmic -rate 48000 -secs 30 [-decimate 3] [-out x.wav]   (ALSA via purego)
//	audiospike capture-exec -dev dsnoopmic -rate 48000 -secs 30 [-decimate 3]                (arecord child)
//	audiospike play         -dev default file.wav                                             (ALSA via purego)
//	audiospike play-exec    -dev default file.wav                                             (aplay child)
//
// Prints one JSON line: CPU% of one core (this process, plus the child for *-exec), RSS/USS.
package main

import (
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"strconv"
	"time"

	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/alsa"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/dsp"
	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/meter"
)

func main() {
	mode := os.Args[1]
	fs := flag.NewFlagSet(mode, flag.ExitOnError)
	dev := fs.String("dev", "default", "ALSA device")
	rate := fs.Int("rate", 48000, "sample rate")
	ch := fs.Int("ch", 1, "channels")
	secs := fs.Float64("secs", 30, "capture seconds")
	dec := fs.Int("decimate", 1, "decimate by N to 16 kHz in Go (3 for 48 kHz)")
	outPath := fs.String("out", "", "write captured (decimated) audio to WAV")
	latency := fs.Int("latency-us", 80000, "ALSA target latency")
	fs.Parse(os.Args[2:])
	res := map[string]any{"mode": mode, "dev": *dev}
	c0, w0 := meter.CPU(), time.Now()
	var child time.Duration
	switch mode {
	case "capture", "capture-exec":
		chunk := *rate / 1000 * 80 * *ch // 80 ms
		buf := make([]int16, chunk)
		var read func([]int16) error
		var done func()
		if mode == "capture" {
			p, err := alsa.Open(*dev, alsa.StreamCapture, *rate, *ch, *latency)
			must(err)
			read, done = p.Read, func() { res["xruns"] = p.Xruns; p.Close() }
		} else {
			cmd := exec.Command("arecord", "-q", "-D", *dev, "-f", "S16_LE", "-r", strconv.Itoa(*rate), "-c", strconv.Itoa(*ch), "-t", "raw", "--buffer-time", strconv.Itoa(*latency))
			so, err := cmd.StdoutPipe()
			must(err)
			must(cmd.Start())
			bb := make([]byte, chunk*2)
			read = func(b []int16) error {
				if _, err := io.ReadFull(so, bb); err != nil {
					return err
				}
				for i := range b {
					b[i] = int16(binary.LittleEndian.Uint16(bb[2*i:]))
				}
				return nil
			}
			done = func() {
				cmd.Process.Signal(os.Interrupt)
				cmd.Wait()
				child = cmd.ProcessState.UserTime() + cmd.ProcessState.SystemTime()
			}
		}
		var d *dsp.Decimator
		if *dec > 1 {
			d = dsp.NewDecimator(*dec)
		}
		var keep []int16
		var sumsq float64
		var peak, n int
		end := time.Now().Add(time.Duration(*secs * float64(time.Second)))
		var dbuf []int16
		for time.Now().Before(end) {
			must(read(buf))
			mono := buf
			if *ch > 1 {
				mono = make([]int16, len(buf) / *ch)
				for i := range mono {
					mono[i] = buf[i**ch]
				}
			}
			for _, s := range mono {
				sumsq += float64(s) * float64(s)
				peak = max(peak, abs(int(s)))
			}
			n += len(mono)
			if d != nil {
				dbuf = d.Process(mono, dbuf[:0])
				mono = dbuf
			}
			if *outPath != "" {
				keep = append(keep, mono...)
			}
		}
		done()
		res["samples"] = n
		res["rms"] = math.Sqrt(sumsq / float64(max(n, 1)))
		res["peak"] = peak
		if *outPath != "" {
			f, err := os.Create(*outPath)
			must(err)
			r := *rate
			if d != nil {
				r /= *dec
			}
			must(meter.WriteWAV(f, keep, r, 1))
			f.Close()
		}
	case "play", "play-exec":
		s, r, c, err := meter.ReadWAV(fs.Arg(0))
		must(err)
		res["audio_s"] = float64(len(s)) / float64(r*c)
		if mode == "play" {
			p, err := alsa.Open(*dev, alsa.StreamPlayback, r, c, *latency)
			must(err)
			step := r / 1000 * 20 * c // 20 ms writes, like a streamed TTS body
			for i := 0; i < len(s); i += step {
				must(p.Write(s[i:min(len(s), i+step)]))
			}
			p.Drain()
			res["xruns"] = p.Xruns
			p.Close()
		} else {
			cmd := exec.Command("aplay", "-q", "-D", *dev, fs.Arg(0))
			must(cmd.Run())
			child = cmd.ProcessState.UserTime() + cmd.ProcessState.SystemTime()
		}
	default:
		must(fmt.Errorf("unknown mode"))
	}
	wall := time.Since(w0)
	self := meter.CPU() - c0
	res["wall_s"] = wall.Seconds()
	res["cpu_pct_self"] = 100 * self.Seconds() / wall.Seconds()
	res["cpu_pct_child"] = 100 * child.Seconds() / wall.Seconds()
	res["mem"] = meter.ReadMem().String()
	b, _ := json.Marshal(res)
	fmt.Println(string(b))
}

func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
