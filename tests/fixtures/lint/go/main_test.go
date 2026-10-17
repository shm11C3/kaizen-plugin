package main

import "testing"

func TestFare(t *testing.T) {
	if fare(500, 0) != 500 || fare(500, 2) != 600 {
		t.Fatal("incorrect fare")
	}
}
