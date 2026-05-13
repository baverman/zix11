const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const mod = b.addModule("zix11", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
    });

    const simple_window = b.addExecutable(.{
        .name = "simple_window",
        .root_module = b.createModule(.{
            .root_source_file = b.path("examples/simple_window.zig"),
            .target = target,
            .optimize = optimize,
            .imports = &.{
                .{ .name = "zix11", .module = mod },
            },
        }),
    });
    b.installArtifact(simple_window);

    const read_properties = b.addExecutable(.{
        .name = "read_properties",
        .root_module = b.createModule(.{
            .root_source_file = b.path("examples/read_properties.zig"),
            .target = target,
            .optimize = optimize,
            .imports = &.{
                .{ .name = "zix11", .module = mod },
            },
        }),
    });
    b.installArtifact(read_properties);

    const mod_tests = b.addTest(.{
        .root_module = mod,
    });
    const run_mod_tests = b.addRunArtifact(mod_tests);

    const test_step = b.step("test", "Run tests");
    test_step.dependOn(&run_mod_tests.step);
}
