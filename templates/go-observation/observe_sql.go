package main

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"strings"
	"sync"

	"github.com/XSAM/otelsql"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric/noop"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

func kaizenSQLOperation(query string) string {
	words := strings.Fields(query)
	if len(words) > 0 {
		switch operation := strings.ToUpper(words[0]); operation {
		case "SELECT", "INSERT", "UPDATE", "DELETE", "REPLACE", "BEGIN", "COMMIT", "ROLLBACK", "CREATE", "ALTER", "DROP", "EXPLAIN", "SHOW", "SET":
			return operation
		}
	}
	return "OTHER"
}

// The application's normal driver must be imported as before. Use Context SQL
// methods and pass request.Context through sqlx/transactions to preserve parents.
func (observer *kaizenObserver) Open(driverName, dsn string) (*sql.DB, error) {
	if !observer.enabled {
		return sql.Open(driverName, dsn)
	}
	system := "other_sql"
	switch driverName {
	case "mysql", "postgres", "sqlite", "sqlite3":
		system = driverName
	}
	return otelsql.Open(driverName, dsn,
		otelsql.WithTracerProvider(observer.provider), otelsql.WithMeterProvider(noop.NewMeterProvider()),
		otelsql.WithAttributes(attribute.String("db.system.name", system)),
		otelsql.WithSpanOptions(otelsql.SpanOptions{DisableQuery: true, DisableErrSkip: true,
			OmitConnResetSession: true, OmitConnPrepare: true, OmitConnectorConnect: true}),
		otelsql.WithSpanNameFormatter(func(_ context.Context, method otelsql.Method, _ string) string { return string(method) }),
		otelsql.WithAttributesGetter(func(_ context.Context, _ otelsql.Method, query string, _ []driver.NamedValue) []attribute.KeyValue {
			return []attribute.KeyValue{attribute.String("db.operation.name", kaizenSQLOperation(query))}
		}),
	)
}

// This wraps the official exporter, not the SQL driver. SDK instrumentation can
// produce URL/user-agent/error text; only the declared safe fields reach disk.
type kaizenPrivateExporter struct {
	sdktrace.SpanExporter
	mu      sync.Mutex
	failure error
}

func (exporter *kaizenPrivateExporter) ExportSpans(ctx context.Context, spans []sdktrace.ReadOnlySpan) error {
	safe := make([]sdktrace.ReadOnlySpan, len(spans))
	for i, span := range spans {
		safe[i] = kaizenPrivateSpan{ReadOnlySpan: span}
	}
	err := exporter.SpanExporter.ExportSpans(ctx, safe)
	if err != nil {
		exporter.mu.Lock()
		if exporter.failure == nil {
			exporter.failure = err
		}
		exporter.mu.Unlock()
	}
	return err
}

type kaizenPrivateSpan struct{ sdktrace.ReadOnlySpan }

func (span kaizenPrivateSpan) Attributes() []attribute.KeyValue {
	var safe []attribute.KeyValue
	for _, item := range span.ReadOnlySpan.Attributes() {
		switch string(item.Key) {
		case "http.request.method", "http.method":
			safe = append(safe, attribute.String("http.request.method", kaizenHTTPMethod(item.Value.AsString())))
		case "http.response.status_code", "http.status_code":
			safe = append(safe, attribute.Int64("http.response.status_code", item.Value.AsInt64()))
		case "http.route", "db.system.name", "db.operation.name":
			safe = append(safe, item)
		}
	}
	return safe
}
func (span kaizenPrivateSpan) Events() []sdktrace.Event { return nil }
func (span kaizenPrivateSpan) Links() []sdktrace.Link   { return nil }
func (span kaizenPrivateSpan) Status() sdktrace.Status {
	status := span.ReadOnlySpan.Status()
	status.Description = ""
	return status
}
func (span kaizenPrivateSpan) Resource() *resource.Resource {
	return resource.NewSchemaless(attribute.String("service.name", "kaizen-observation"))
}

func kaizenTraceContext(value trace.SpanContext) trace.SpanContext {
	return trace.NewSpanContext(trace.SpanContextConfig{TraceID: value.TraceID(), SpanID: value.SpanID(), TraceFlags: value.TraceFlags(), Remote: value.IsRemote()})
}
func (span kaizenPrivateSpan) SpanContext() trace.SpanContext {
	return kaizenTraceContext(span.ReadOnlySpan.SpanContext())
}
func (span kaizenPrivateSpan) Parent() trace.SpanContext {
	return kaizenTraceContext(span.ReadOnlySpan.Parent())
}

func (exporter *kaizenPrivateExporter) Error() error {
	exporter.mu.Lock()
	defer exporter.mu.Unlock()
	return exporter.failure
}
