// hat drives the ReSpeaker 2-mic HAT's non-audio parts from pure Go (CGO_ENABLED=0):
// the 3 APA102 LEDs on /dev/spidev0.0 (raw spidev write, ~1 ioctl) and the button on GPIO17
// via the gpiochip character device (go-gpiocdev; sysfs GPIO is deprecated).
//
//	hat leds R G B BRIGHTNESS(0-31) SECONDS   then turns them off
//	hat button SECONDS                        prints the level and any edges
package main

import (
	"fmt"
	"os"
	"strconv"
	"time"
	"unsafe"

	"github.com/warthog618/go-gpiocdev"
	"golang.org/x/sys/unix"
)

const spiIOCWrMaxSpeedHz = 0x40046b04 // _IOW('k', 4, __u32)

func apa102Frame(n int, r, g, b, bright byte) []byte {
	f := make([]byte, 4, 4+4*n+4)
	for i := 0; i < n; i++ {
		f = append(f, 0xE0|(bright&0x1F), b, g, r)
	}
	return append(f, 0xFF, 0xFF, 0xFF, 0xFF)
}

func leds(args []string) error {
	v := make([]int, 5)
	for i := range v {
		v[i], _ = strconv.Atoi(args[i])
	}
	f, err := os.OpenFile("/dev/spidev0.0", os.O_RDWR, 0)
	if err != nil {
		return err
	}
	defer f.Close()
	hz := uint32(8_000_000)
	if _, _, e := unix.Syscall(unix.SYS_IOCTL, f.Fd(), spiIOCWrMaxSpeedHz, uintptr(unsafe.Pointer(&hz))); e != 0 {
		return e
	}
	if _, err := f.Write(apa102Frame(3, byte(v[0]), byte(v[1]), byte(v[2]), byte(v[3]))); err != nil {
		return err
	}
	time.Sleep(time.Duration(v[4]) * time.Second)
	_, err = f.Write(apa102Frame(3, 0, 0, 0, 0))
	return err
}

func button(secs int) error {
	l, err := gpiocdev.RequestLine("gpiochip0", 17, gpiocdev.AsInput, gpiocdev.WithPullUp, gpiocdev.WithBothEdges,
		gpiocdev.WithEventHandler(func(e gpiocdev.LineEvent) { fmt.Printf("edge %v at %v\n", e.Type, e.Timestamp) }))
	if err != nil {
		return err
	}
	defer l.Close()
	v, err := l.Value()
	fmt.Println("GPIO17 level:", v, err)
	time.Sleep(time.Duration(secs) * time.Second)
	return nil
}

func main() {
	var err error
	switch os.Args[1] {
	case "leds":
		err = leds(os.Args[2:])
	case "button":
		s, _ := strconv.Atoi(os.Args[2])
		err = button(s)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
