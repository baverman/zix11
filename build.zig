const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const mod = b.addModule("zix11", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
    });

    addExample(b, "simple_window", "examples/simple_window.zig", target, optimize, mod, false);
    addExample(b, "read_properties", "examples/read_properties.zig", target, optimize, mod, false);
    addExample(b, "dpms", "examples/dpms.zig", target, optimize, mod, false);
    addExample(b, "randr", "examples/randr.zig", target, optimize, mod, false);
    addExample(b, "xinput", "examples/xinput.zig", target, optimize, mod, false);
    addExample(b, "xkb", "examples/xkb.zig", target, optimize, mod, false);
    addExample(b, "cairo", "examples/cairo.zig", target, optimize, mod, true);
    addExample(b, "cairo_shm", "examples/cairo_shm.zig", target, optimize, mod, true);
    addExample(b, "cairo_animation", "examples/cairo_animation.zig", target, optimize, mod, true);
    addExample(b, "transparent", "examples/transparent.zig", target, optimize, mod, true);

    const root_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/root_test.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const run_root_tests = b.addRunArtifact(root_tests);

    const test_step = b.step("test", "Run tests");
    test_step.dependOn(&run_root_tests.step);
}

fn addExample(
    b: *std.Build,
    name: []const u8,
    path: []const u8,
    target: std.Build.ResolvedTarget,
    optimize: std.builtin.OptimizeMode,
    mod: *std.Build.Module,
    link_cairo: bool,
) void {
    const exe = b.addExecutable(.{
        .name = name,
        .root_module = b.createModule(.{
            .root_source_file = b.path(path),
            .target = target,
            .optimize = optimize,
            .link_libc = link_cairo,
            .imports = &.{
                .{ .name = "zix11", .module = mod },
            },
        }),
    });
    if (link_cairo) {
        exe.root_module.linkSystemLibrary("cairo", .{ .use_pkg_config = .force });
    }
    b.installArtifact(exe);
}
