.PHONY: test-msb build-msb generate test fmt

test-msb:
	zig build test -fqemu -Dtarget=powerpc-linux-musl

build-msb:
	zig build -Dtarget=powerpc-linux-musl

generate:
	python -m genproto
	python -m genproto.test_generator

test:
	zig test src/generator_test.zig
	zig test src/gen_xproto_test.zig
	zig build test

fmt:
	ruff check --select I --fix genproto
	ruff format genproto
	zig fmt src/ examples/
