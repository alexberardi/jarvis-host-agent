// Package ort is a minimal onnxruntime C API binding over purego (no cgo): enough to run
// float32/int64 models with named inputs and outputs. Function-table indices are for
// ORT_API_VERSION 28 (onnxruntime 1.28.x, the build jarvisd embeds); the OrtApi table is
// append-only, so these indices hold for any newer runtime too.
package ort

import (
	"errors"
	"fmt"
	"runtime"
	"unsafe"

	"github.com/ebitengine/purego"
)

// OrtApi slot indices (computed from onnxruntime_c_api.h v1.28.2 by spikes/pinode/tools/ortidx.py).
const (
	iGetErrorMessage                  = 2
	iCreateEnv                        = 3
	iCreateSession                    = 7
	iRun                              = 9
	iCreateSessionOptions             = 10
	iDisableCpuMemArena               = 19
	iSetSessionGraphOptimizationLevel = 23
	iSetIntraOpNumThreads             = 24
	iSetInterOpNumThreads             = 25
	iCreateTensorWithDataAsOrtValue   = 49
	iGetTensorMutableData             = 51
	iGetDimensionsCount               = 61
	iGetDimensions                    = 62
	iGetTensorTypeAndShape            = 65
	iCreateCpuMemoryInfo              = 69
	iReleaseStatus                    = 93
	iReleaseValue                     = 96
	iReleaseTensorTypeAndShapeInfo    = 99
	iReleaseSessionOptions            = 100
)

const apiVersion = 28

const (
	TypeFloat = 1
	TypeInt64 = 7
)

type Runtime struct {
	api     uintptr
	env     uintptr
	memInfo uintptr
	Version string
}

func (r *Runtime) fn(i int) uintptr {
	return *(*uintptr)(unsafe.Add(unsafe.Pointer(r.api), i*int(unsafe.Sizeof(uintptr(0)))))
}

func (r *Runtime) call(i int, args ...uintptr) error {
	st, _, _ := purego.SyscallN(r.fn(i), args...)
	if st == 0 {
		return nil
	}
	msg, _, _ := purego.SyscallN(r.fn(iGetErrorMessage), st)
	err := errors.New("onnxruntime: " + goString(msg))
	purego.SyscallN(r.fn(iReleaseStatus), st)
	return err
}

func goString(p uintptr) string {
	if p == 0 {
		return ""
	}
	var b []byte
	for {
		c := *(*byte)(unsafe.Pointer(p))
		if c == 0 {
			return string(b)
		}
		b = append(b, c)
		p++
	}
}

type cstrs struct{ bufs [][]byte }

func (c *cstrs) of(s string) uintptr {
	b := append([]byte(s), 0)
	c.bufs = append(c.bufs, b)
	return uintptr(unsafe.Pointer(&b[0]))
}

// Load dlopens libonnxruntime at path and creates one process-wide environment.
func Load(path string) (*Runtime, error) {
	h, err := purego.Dlopen(path, purego.RTLD_NOW|purego.RTLD_GLOBAL)
	if err != nil {
		return nil, fmt.Errorf("dlopen %s: %w", path, err)
	}
	sym, err := purego.Dlsym(h, "OrtGetApiBase")
	if err != nil {
		return nil, err
	}
	base, _, _ := purego.SyscallN(sym)
	getAPI := *(*uintptr)(unsafe.Pointer(base))
	getVer := *(*uintptr)(unsafe.Add(unsafe.Pointer(base), unsafe.Sizeof(uintptr(0))))
	v, _, _ := purego.SyscallN(getVer)
	r := &Runtime{Version: goString(v)}
	r.api, _, _ = purego.SyscallN(getAPI, apiVersion)
	if r.api == 0 {
		return nil, fmt.Errorf("onnxruntime %s does not offer C API v%d", r.Version, apiVersion)
	}
	var cs cstrs
	if err := r.call(iCreateEnv, 3 /*ERROR*/, cs.of("pinode"), uintptr(unsafe.Pointer(&r.env))); err != nil {
		return nil, err
	}
	// OrtDeviceAllocator (0), OrtMemTypeDefault (0): input tensors wrap caller-owned Go memory.
	if err := r.call(iCreateCpuMemoryInfo, 0, 0, uintptr(unsafe.Pointer(&r.memInfo))); err != nil {
		return nil, err
	}
	runtime.KeepAlive(cs)
	return r, nil
}

// Session is one loaded model with fixed input/output names.
type Session struct {
	r                 *Runtime
	h                 uintptr
	inNames, outNames []uintptr
	names             cstrs
}

type Options struct {
	Threads int  // intra- and inter-op threads; oww uses 1
	NoArena bool // DisableCpuMemArena: trades a little speed for a smaller footprint
}

func (r *Runtime) NewSession(model string, in, out []string, o Options) (*Session, error) {
	var opts uintptr
	if err := r.call(iCreateSessionOptions, uintptr(unsafe.Pointer(&opts))); err != nil {
		return nil, err
	}
	defer purego.SyscallN(r.fn(iReleaseSessionOptions), opts)
	t := o.Threads
	if t <= 0 {
		t = 1
	}
	if err := r.call(iSetIntraOpNumThreads, opts, uintptr(t)); err != nil {
		return nil, err
	}
	if err := r.call(iSetInterOpNumThreads, opts, uintptr(t)); err != nil {
		return nil, err
	}
	if err := r.call(iSetSessionGraphOptimizationLevel, opts, 99); err != nil {
		return nil, err
	}
	if o.NoArena {
		if err := r.call(iDisableCpuMemArena, opts); err != nil {
			return nil, err
		}
	}
	s := &Session{r: r}
	var cs cstrs
	if err := r.call(iCreateSession, r.env, cs.of(model), opts, uintptr(unsafe.Pointer(&s.h))); err != nil {
		return nil, fmt.Errorf("%s: %w", model, err)
	}
	for _, n := range in {
		s.inNames = append(s.inNames, s.names.of(n))
	}
	for _, n := range out {
		s.outNames = append(s.outNames, s.names.of(n))
	}
	return s, nil
}

// Tensor is an input: exactly one of F32/I64 is set.
type Tensor struct {
	Shape []int64
	F32   []float32
	I64   []int64
}

// Output is a float32 output tensor copied into Go memory.
type Output struct {
	Shape []int64
	Data  []float32
}

// Run feeds inputs (in the session's input-name order) and returns float32 outputs.
func (s *Session) Run(inputs ...Tensor) ([]Output, error) {
	r := s.r
	vals := make([]uintptr, len(inputs))
	defer func() {
		for _, v := range vals {
			if v != 0 {
				purego.SyscallN(r.fn(iReleaseValue), v)
			}
		}
	}()
	for i, t := range inputs {
		var p unsafe.Pointer
		var n, typ uintptr
		switch {
		case t.I64 != nil:
			p, n, typ = unsafe.Pointer(&t.I64[0]), uintptr(len(t.I64)*8), TypeInt64
		default:
			p, n, typ = unsafe.Pointer(&t.F32[0]), uintptr(len(t.F32)*4), TypeFloat
		}
		var shapeP uintptr
		if len(t.Shape) > 0 {
			shapeP = uintptr(unsafe.Pointer(&t.Shape[0]))
		}
		if err := r.call(iCreateTensorWithDataAsOrtValue, r.memInfo, uintptr(p), n, shapeP, uintptr(len(t.Shape)), typ, uintptr(unsafe.Pointer(&vals[i]))); err != nil {
			return nil, err
		}
	}
	outs := make([]uintptr, len(s.outNames))
	err := r.call(iRun, s.h, 0,
		uintptr(unsafe.Pointer(&s.inNames[0])), uintptr(unsafe.Pointer(&vals[0])), uintptr(len(vals)),
		uintptr(unsafe.Pointer(&s.outNames[0])), uintptr(len(outs)), uintptr(unsafe.Pointer(&outs[0])))
	runtime.KeepAlive(inputs)
	runtime.KeepAlive(s)
	if err != nil {
		return nil, err
	}
	res := make([]Output, len(outs))
	for i, v := range outs {
		res[i], err = r.read(v)
		purego.SyscallN(r.fn(iReleaseValue), v)
		if err != nil {
			return nil, err
		}
	}
	return res, nil
}

func (r *Runtime) read(v uintptr) (Output, error) {
	var info uintptr
	if err := r.call(iGetTensorTypeAndShape, v, uintptr(unsafe.Pointer(&info))); err != nil {
		return Output{}, err
	}
	defer purego.SyscallN(r.fn(iReleaseTensorTypeAndShapeInfo), info)
	var nd uintptr
	if err := r.call(iGetDimensionsCount, info, uintptr(unsafe.Pointer(&nd))); err != nil {
		return Output{}, err
	}
	shape := make([]int64, nd)
	if nd > 0 {
		if err := r.call(iGetDimensions, info, uintptr(unsafe.Pointer(&shape[0])), nd); err != nil {
			return Output{}, err
		}
	}
	n := int64(1)
	for _, d := range shape {
		n *= d
	}
	var p uintptr
	if err := r.call(iGetTensorMutableData, v, uintptr(unsafe.Pointer(&p))); err != nil {
		return Output{}, err
	}
	data := make([]float32, n)
	copy(data, unsafe.Slice((*float32)(unsafe.Pointer(p)), n))
	return Output{Shape: shape, Data: data}, nil
}
