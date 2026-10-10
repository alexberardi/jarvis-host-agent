// Package meter has the spike's measuring helpers: process CPU time and RSS/USS, and WAV I/O.
package meter

import (
	"bufio"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// CPU returns user+system CPU time consumed by this process so far.
func CPU() time.Duration {
	var ru syscall.Rusage
	_ = syscall.Getrusage(syscall.RUSAGE_SELF, &ru)
	return time.Duration(ru.Utime.Nano() + ru.Stime.Nano())
}

// Mem is RSS and USS (private clean+dirty) in MiB, from /proc/self/smaps_rollup.
type Mem struct{ RSS, USS float64 }

func (m Mem) String() string { return fmt.Sprintf("rss=%.1fMiB uss=%.1fMiB", m.RSS, m.USS) }

func ReadMem() Mem { return ReadMemPID("self") }

func ReadMemPID(pid string) Mem {
	f, err := os.Open("/proc/" + pid + "/smaps_rollup")
	if err != nil {
		return Mem{}
	}
	defer f.Close()
	var m Mem
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		k, v, ok := strings.Cut(sc.Text(), ":")
		if !ok {
			continue
		}
		fs := strings.Fields(v)
		if len(fs) == 0 {
			continue
		}
		kb, _ := strconv.ParseFloat(fs[0], 64)
		switch k {
		case "Rss":
			m.RSS = kb / 1024
		case "Private_Clean", "Private_Dirty":
			m.USS += kb / 1024
		}
	}
	return m
}

// ReadWAV reads a 16-bit PCM WAV and returns interleaved samples, rate and channels.
func ReadWAV(path string) ([]int16, int, int, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, 0, 0, err
	}
	if len(b) < 12 || string(b[:4]) != "RIFF" || string(b[8:12]) != "WAVE" {
		return nil, 0, 0, errors.New("not a WAV")
	}
	var rate, ch int
	p := 12
	for p+8 <= len(b) {
		id, sz := string(b[p:p+4]), int(binary.LittleEndian.Uint32(b[p+4:]))
		body := b[p+8 : min(len(b), p+8+sz)]
		switch id {
		case "fmt ":
			if binary.LittleEndian.Uint16(body[0:]) != 1 || binary.LittleEndian.Uint16(body[14:]) != 16 {
				return nil, 0, 0, errors.New("only 16-bit PCM")
			}
			ch = int(binary.LittleEndian.Uint16(body[2:]))
			rate = int(binary.LittleEndian.Uint32(body[4:]))
		case "data":
			s := make([]int16, len(body)/2)
			for i := range s {
				s[i] = int16(binary.LittleEndian.Uint16(body[2*i:]))
			}
			return s, rate, ch, nil
		}
		p += 8 + sz + sz%2
	}
	return nil, 0, 0, errors.New("no data chunk")
}

// WriteWAV writes 16-bit PCM.
func WriteWAV(w io.Writer, s []int16, rate, ch int) error {
	h := make([]byte, 44)
	copy(h, "RIFF")
	binary.LittleEndian.PutUint32(h[4:], uint32(36+len(s)*2))
	copy(h[8:], "WAVEfmt ")
	binary.LittleEndian.PutUint32(h[16:], 16)
	binary.LittleEndian.PutUint16(h[20:], 1)
	binary.LittleEndian.PutUint16(h[22:], uint16(ch))
	binary.LittleEndian.PutUint32(h[24:], uint32(rate))
	binary.LittleEndian.PutUint32(h[28:], uint32(rate*ch*2))
	binary.LittleEndian.PutUint16(h[32:], uint16(ch*2))
	binary.LittleEndian.PutUint16(h[34:], 16)
	copy(h[36:], "data")
	binary.LittleEndian.PutUint32(h[40:], uint32(len(s)*2))
	if _, err := w.Write(h); err != nil {
		return err
	}
	return binary.Write(w, binary.LittleEndian, s)
}
