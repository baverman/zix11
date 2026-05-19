.PHONY: test-msb
test-msb:
	zig build test -fqemu -Dtarget=powerpc-linux-musl
build-msb:
	zig build -Dtarget=powerpc-linux-musl
