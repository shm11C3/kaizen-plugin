package main

import "log/slog"

func fare(base, distance int) int {
	return base + max(distance-1, 0)*100
}

func main() {
	slog.Info("fare", "value", fare(500, 2))
}
