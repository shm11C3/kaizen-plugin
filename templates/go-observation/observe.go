// Copy into an isolated Go observation candidate, then wrap the application's
// handler with kaizenObserve(handler). No observer runs without the private flag.
package main

import (
	"log/slog"
	"net/http"
	"net/http/pprof"
	"os"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/stdout/stdouttrace"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

func kaizenObserve(next http.Handler) http.Handler {
	flag := os.Getenv("KAIZEN_OBSERVE_FLAG")
	if flag == "" {
		flag = "/var/tmp/kaizen-observation-enabled"
	}
	if _, err := os.Stat(flag); err != nil {
		return next
	}
	sink := os.Getenv("KAIZEN_TRACE_FILE")
	if sink == "" {
		sink = "/var/tmp/kaizen-observation-traces.jsonl"
	}
	f, err := os.OpenFile(sink, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0600)
	if err != nil {
		slog.Error("observation sink unavailable", "error", err)
		return next
	}
	exporter, err := stdouttrace.New(stdouttrace.WithWriter(f))
	if err != nil {
		f.Close()
		slog.Error("observation exporter unavailable", "error", err)
		return next
	}
	// Synchronous export avoids losing a batch when the practice app is restarted.
	// Sampled file I/O has a cost: every run with the flag on is observation only.
	provider := sdktrace.NewTracerProvider(sdktrace.WithSampler(sdktrace.TraceIDRatioBased(0.01)), sdktrace.WithSyncer(exporter))
	otel.SetTracerProvider(provider)
	tracer := provider.Tracer("kaizen-observation")
	profiler := http.NewServeMux()
	profiler.HandleFunc("/debug/pprof/", pprof.Index)
	profiler.HandleFunc("/debug/pprof/profile", pprof.Profile)
	profiler.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
	profiler.HandleFunc("/debug/pprof/trace", pprof.Trace)
	go func() {
		server := &http.Server{Addr: "127.0.0.1:6060", Handler: profiler, ReadHeaderTimeout: 5 * time.Second}
		if err := server.ListenAndServe(); err != nil {
			slog.Error("private profile listener unavailable", "error", err)
		}
	}()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := propagation.TraceContext{}.Extract(r.Context(), propagation.HeaderCarrier(r.Header))
		ctx, span := tracer.Start(ctx, "HTTP "+r.Method, trace.WithSpanKind(trace.SpanKindServer), trace.WithAttributes(attribute.String("http.request.method", r.Method)))
		defer span.End()
		// Do not record raw query strings, headers, bodies or path identifiers.
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
