// Package alsa is a minimal libasound binding over purego (no cgo): open a PCM by name
// (so asound.conf devices like dsnoopmic/dmix/plug work), set S16_LE interleaved params,
// and read/write frames. Every call is a plain int/pointer C call.
package alsa

import (
	"fmt"
	"sync"
	"unsafe"

	"github.com/ebitengine/purego"
)

const (
	StreamPlayback = 0
	StreamCapture  = 1
	formatS16LE    = 2
	accessRWInterl = 3
)

var (
	once          sync.Once
	loadErr       error
	sndPcmOpen    func(pcm *uintptr, name *byte, stream, mode int32) int32
	sndPcmSetPar  func(pcm uintptr, format, access int32, channels, rate uint32, softResample int32, latencyUS uint32) int32
	sndPcmReadi   func(pcm uintptr, buf unsafe.Pointer, frames uint64) int64
	sndPcmWritei  func(pcm uintptr, buf unsafe.Pointer, frames uint64) int64
	sndPcmRecover func(pcm uintptr, err, silent int32) int32
	sndPcmDrain   func(pcm uintptr) int32
	sndPcmClose   func(pcm uintptr) int32
	sndStrerror   func(err int32) string
)

func load() error {
	once.Do(func() {
		h, err := purego.Dlopen("libasound.so.2", purego.RTLD_NOW|purego.RTLD_GLOBAL)
		if err != nil {
			loadErr = fmt.Errorf("libasound: %w", err)
			return
		}
		purego.RegisterLibFunc(&sndPcmOpen, h, "snd_pcm_open")
		purego.RegisterLibFunc(&sndPcmSetPar, h, "snd_pcm_set_params")
		purego.RegisterLibFunc(&sndPcmReadi, h, "snd_pcm_readi")
		purego.RegisterLibFunc(&sndPcmWritei, h, "snd_pcm_writei")
		purego.RegisterLibFunc(&sndPcmRecover, h, "snd_pcm_recover")
		purego.RegisterLibFunc(&sndPcmDrain, h, "snd_pcm_drain")
		purego.RegisterLibFunc(&sndPcmClose, h, "snd_pcm_close")
		purego.RegisterLibFunc(&sndStrerror, h, "snd_strerror")
	})
	return loadErr
}

type PCM struct {
	h        uintptr
	Channels int
	Xruns    int // overruns/underruns recovered
}

// Open opens device (e.g. "dsnoopmic", "default", "hw:CARD=Loopback,DEV=1") with the given
// rate/channels and target latency. ALSA's plug layer converts if the device needs it.
func Open(device string, stream int, rate, channels int, latencyUS int) (*PCM, error) {
	if err := load(); err != nil {
		return nil, err
	}
	name := append([]byte(device), 0)
	p := &PCM{Channels: channels}
	if rc := sndPcmOpen(&p.h, &name[0], int32(stream), 0); rc < 0 {
		return nil, fmt.Errorf("snd_pcm_open %s: %s", device, sndStrerror(rc))
	}
	if rc := sndPcmSetPar(p.h, formatS16LE, accessRWInterl, uint32(channels), uint32(rate), 1, uint32(latencyUS)); rc < 0 {
		sndPcmClose(p.h)
		return nil, fmt.Errorf("snd_pcm_set_params %s: %s", device, sndStrerror(rc))
	}
	return p, nil
}

// Read fills buf (interleaved) completely, recovering from overruns.
func (p *PCM) Read(buf []int16) error {
	frames := len(buf) / p.Channels
	got := 0
	for got < frames {
		n := sndPcmReadi(p.h, unsafe.Pointer(&buf[got*p.Channels]), uint64(frames-got))
		if n < 0 {
			p.Xruns++
			if rc := sndPcmRecover(p.h, int32(n), 1); rc < 0 {
				return fmt.Errorf("snd_pcm_readi: %s", sndStrerror(int32(n)))
			}
			continue
		}
		got += int(n)
	}
	return nil
}

// Write plays buf (interleaved), recovering from underruns.
func (p *PCM) Write(buf []int16) error {
	frames := len(buf) / p.Channels
	done := 0
	for done < frames {
		n := sndPcmWritei(p.h, unsafe.Pointer(&buf[done*p.Channels]), uint64(frames-done))
		if n < 0 {
			p.Xruns++
			if rc := sndPcmRecover(p.h, int32(n), 1); rc < 0 {
				return fmt.Errorf("snd_pcm_writei: %s", sndStrerror(int32(n)))
			}
			continue
		}
		done += int(n)
	}
	return nil
}

func (p *PCM) Drain() { sndPcmDrain(p.h) }
func (p *PCM) Close() { sndPcmClose(p.h) }
