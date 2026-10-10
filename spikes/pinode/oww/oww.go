// Package oww is openWakeWord 0.6.0's streaming pipeline (AudioFeatures + Model.predict)
// re-implemented over the ort binding: 16 kHz int16 in 1280-sample (80 ms) chunks →
// melspectrogram.onnx → (x/10+2) → embedding_model.onnx on the last 76 mel frames →
// wake model on the last 16 embeddings. Buffers and their initial values mirror
// openwakeword/utils.py so scores match frame for frame once the feature window has filled.
package oww

import (
	"fmt"
	"path/filepath"
	"time"

	"github.com/alexberardi/jarvis-host-agent/spikes/pinode/ort"
)

const (
	Chunk      = 1280 // samples per prediction step (80 ms @ 16 kHz)
	melBins    = 32
	melWin     = 76
	featDim    = 96
	featWin    = 16
	rawKeep    = 16000 * 10
	melKeep    = 10 * 97
	featKeep   = 120
	melContext = 160 * 3
)

type Detector struct {
	mel, emb, wake *ort.Session
	raw            []int16
	melbuf         [][melBins]float32
	feats          [][featDim]float32
	nPred          int
	// Stage CPU-free wall time spent in each model since New (for profiling).
	TMel, TEmb, TWake time.Duration
}

// New loads the three models from dir (melspectrogram.onnx, embedding_model.onnx, wakeModel).
func New(rt *ort.Runtime, dir, wakeModel string, o ort.Options) (*Detector, error) {
	d := &Detector{}
	var err error
	if d.mel, err = rt.NewSession(filepath.Join(dir, "melspectrogram.onnx"), []string{"input"}, []string{"output"}, o); err != nil {
		return nil, err
	}
	if d.emb, err = rt.NewSession(filepath.Join(dir, "embedding_model.onnx"), []string{"input_1"}, []string{"conv2d_19"}, o); err != nil {
		return nil, err
	}
	if d.wake, err = rt.NewSession(filepath.Join(dir, wakeModel), []string{"x.1"}, []string{"53"}, o); err != nil {
		return nil, err
	}
	d.Reset()
	return d, nil
}

func (d *Detector) Reset() {
	d.raw = d.raw[:0]
	d.melbuf = make([][melBins]float32, melWin)
	for i := range d.melbuf {
		for j := range d.melbuf[i] {
			d.melbuf[i][j] = 1 // np.ones((76, 32))
		}
	}
	d.feats = d.feats[:0]
	d.nPred = 0
}

// Process takes exactly one 1280-sample chunk and returns the wake score (0 until the
// 16-embedding window has filled; oww also zeroes its first 5 predictions).
func (d *Detector) Process(chunk []int16) (float32, error) {
	if len(chunk) != Chunk {
		return 0, fmt.Errorf("chunk must be %d samples", Chunk)
	}
	d.raw = append(d.raw, chunk...)
	if len(d.raw) > rawKeep {
		d.raw = append(d.raw[:0], d.raw[len(d.raw)-rawKeep:]...)
	}
	n := min(len(d.raw), Chunk+melContext)
	in := make([]float32, n)
	for i, s := range d.raw[len(d.raw)-n:] {
		in[i] = float32(s)
	}
	t0 := time.Now()
	out, err := d.mel.Run(ort.Tensor{Shape: []int64{1, int64(n)}, F32: in})
	if err != nil {
		return 0, err
	}
	d.TMel += time.Since(t0)
	m := out[0].Data
	for i := 0; i+melBins <= len(m); i += melBins {
		var row [melBins]float32
		for j := range row {
			row[j] = m[i+j]/10 + 2
		}
		d.melbuf = append(d.melbuf, row)
	}
	if len(d.melbuf) > melKeep {
		d.melbuf = append(d.melbuf[:0], d.melbuf[len(d.melbuf)-melKeep:]...)
	}
	win := make([]float32, 0, melWin*melBins)
	for _, row := range d.melbuf[len(d.melbuf)-melWin:] {
		win = append(win, row[:]...)
	}
	t0 = time.Now()
	eo, err := d.emb.Run(ort.Tensor{Shape: []int64{1, melWin, melBins, 1}, F32: win})
	if err != nil {
		return 0, err
	}
	d.TEmb += time.Since(t0)
	var f [featDim]float32
	copy(f[:], eo[0].Data)
	d.feats = append(d.feats, f)
	if len(d.feats) > featKeep {
		d.feats = append(d.feats[:0], d.feats[len(d.feats)-featKeep:]...)
	}
	if len(d.feats) < featWin {
		return 0, nil
	}
	x := make([]float32, 0, featWin*featDim)
	for _, r := range d.feats[len(d.feats)-featWin:] {
		x = append(x, r[:]...)
	}
	t0 = time.Now()
	wo, err := d.wake.Run(ort.Tensor{Shape: []int64{1, featWin, featDim}, F32: x})
	if err != nil {
		return 0, err
	}
	d.TWake += time.Since(t0)
	d.nPred++
	if d.nPred <= 5 {
		return 0, nil
	}
	return wo[0].Data[0], nil
}
