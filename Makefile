.PHONY: test-msb build-msb generate
test-msb:
	zig build test -fqemu -Dtarget=powerpc-linux-musl

build-msb:
	zig build -Dtarget=powerpc-linux-musl

generate:
	python -m genproto
	python -m genproto.test_generator
