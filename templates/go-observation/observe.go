// Copy both observe*.go files into a Go observation candidate (package main).
// Initialize once, wrap HTTP + sql.Open, and Shutdown after draining the app.
package main

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"runtime/pprof"
	"strconv"
	"sync"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/stdout/stdouttrace"
	"go.opentelemetry.io/otel/metric/noop"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

type kaizenObserver struct {
	enabled       bool
	provider      *sdktrace.TracerProvider
	exporter      *kaizenPrivateExporter
	sink          *os.File
	profiler      *http.Server
	listener      net.Listener
	once          sync.Once
	shutdownError error
}

func kaizenEnv(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func newKaizenObserver() (*kaizenObserver, error) {
	observer := &kaizenObserver{}
	flag := kaizenEnv("KAIZEN_OBSERVE_FLAG", "/var/tmp/kaizen-observation-enabled")
	info, err := os.Stat(flag)
	if errors.Is(err, os.ErrNotExist) {
		return observer, nil
	}
	if err != nil {
		return nil, fmt.Errorf("observation flag: %w", err)
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("observation flag must be a regular file")
	}
	ratio, err := strconv.ParseFloat(kaizenEnv("KAIZEN_TRACE_RATIO", "0.01"), 64)
	if err != nil || !(ratio > 0 && ratio <= 1) {
		return nil, errors.New("KAIZEN_TRACE_RATIO must be >0 and <=1")
	}
	address := kaizenEnv("KAIZEN_PPROF_ADDR", "127.0.0.1:6060")
	host, _, err := net.SplitHostPort(address)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		return nil, errors.New("KAIZEN_PPROF_ADDR must use a literal loopback IP")
	}
	path := kaizenEnv("KAIZEN_TRACE_FILE", "/var/tmp/kaizen-observation-traces.jsonl")
	if stat, err := os.Lstat(path); err == nil && !stat.Mode().IsRegular() {
		return nil, errors.New("trace sink must be a regular file, not a symlink/device")
	} else if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	sink, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0600)
	if err != nil {
		return nil, fmt.Errorf("observation sink: %w", err)
	}
	if err := sink.Chmod(0600); err != nil {
		sink.Close()
		return nil, err
	}
	exporter, err := stdouttrace.New(stdouttrace.WithWriter(sink))
	if err != nil {
		sink.Close()
		return nil, err
	}
	// Use official JSON export; sanitize all persisted span fields at its boundary.
	privateExporter := &kaizenPrivateExporter{SpanExporter: exporter}
	provider := sdktrace.NewTracerProvider(
		sdktrace.WithResource(resource.NewSchemaless(attribute.String("service.name", "kaizen-observation"))),
		sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.TraceIDRatioBased(ratio))),
		sdktrace.WithSyncer(privateExporter),
	)
	listener, err := net.Listen("tcp", address)
	if err != nil {
		provider.Shutdown(context.Background())
		sink.Close()
		return nil, fmt.Errorf("private pprof bind: %w", err)
	}
	mux := kaizenProfileMux()
	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	observer.enabled, observer.provider, observer.sink = true, provider, sink
	observer.exporter = privateExporter
	observer.profiler, observer.listener = server, listener
	go server.Serve(listener) // Listener has already bound synchronously; Shutdown owns its lifetime.
	return observer, nil
}

func (observer *kaizenObserver) Enabled() bool { return observer.enabled }

func (observer *kaizenObserver) ProfileAddress() string {
	if observer.listener == nil {
		return ""
	}
	return observer.listener.Addr().String()
}

func kaizenHTTPMethod(method string) string {
	switch method {
	case "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE":
		return method
	default:
		return "OTHER"
	}
}

// route must be a static router pattern (e.g. /api/rides/{id}), never RequestURI.
// No headers, URLs, bodies, application IDs, DB arguments or SQL are exported.
func (observer *kaizenObserver) Handler(route string, next http.Handler) http.Handler {
	if !observer.enabled {
		return next
	}
	tagged := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		trace.SpanFromContext(r.Context()).SetAttributes(attribute.String("http.route", route))
		next.ServeHTTP(w, r)
	})
	return otelhttp.NewHandler(tagged, route,
		otelhttp.WithTracerProvider(observer.provider), otelhttp.WithMeterProvider(noop.NewMeterProvider()),
		otelhttp.WithPropagators(propagation.TraceContext{}),
		otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string { return "HTTP " + kaizenHTTPMethod(r.Method) + " " + route }),
	)
}

// Flush after a diagnostic window; errors must be handled by the operator.
func (observer *kaizenObserver) Flush(ctx context.Context) error {
	if !observer.enabled {
		return nil
	}
	return errors.Join(observer.provider.ForceFlush(ctx), observer.exporter.Error(), observer.sink.Sync())
}

// Drain the application's HTTP server and close DB first. Call once at shutdown.
func (observer *kaizenObserver) Shutdown(ctx context.Context) error {
	observer.once.Do(func() {
		if !observer.enabled {
			return
		}
		serverError := observer.profiler.Shutdown(ctx)
		if serverError != nil {
			observer.profiler.Close()
		}
		observer.shutdownError = errors.Join(serverError, observer.provider.Shutdown(ctx), observer.exporter.Error(), observer.sink.Sync(), observer.sink.Close())
	})
	return observer.shutdownError
}

// runtime/pprof avoids net/http/pprof's init-time registration on the PUBLIC
// DefaultServeMux, including when observation is off. Go tool pprof reads these
// standard runtime profiles directly; no public router is modified.
func kaizenProfileMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/debug/pprof/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/debug/pprof/" {
			http.NotFound(w, r)
			return
		}
		for _, profile := range pprof.Profiles() {
			fmt.Fprintln(w, profile.Name())
		}
	})
	for _, name := range []string{"allocs", "block", "goroutine", "heap", "mutex", "threadcreate"} {
		profile := pprof.Lookup(name)
		mux.HandleFunc("/debug/pprof/"+name, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/octet-stream")
			profile.WriteTo(w, 0)
		})
	}
	mux.HandleFunc("/debug/pprof/profile", func(w http.ResponseWriter, r *http.Request) {
		seconds := 30
		if value := r.URL.Query().Get("seconds"); value != "" {
			n, err := strconv.Atoi(value)
			if err != nil || n < 1 || n > 30 {
				http.Error(w, "seconds must be 1..30", http.StatusBadRequest)
				return
			}
			seconds = n
		}
		w.Header().Set("Content-Type", "application/octet-stream")
		if err := pprof.StartCPUProfile(w); err != nil {
			http.Error(w, "CPU profiler is already active", http.StatusServiceUnavailable)
			return
		}
		defer pprof.StopCPUProfile()
		timer := time.NewTimer(time.Duration(seconds) * time.Second)
		defer timer.Stop()
		select {
		case <-timer.C:
		case <-r.Context().Done():
		}
	})
	return mux
}
