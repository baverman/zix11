const std = @import("std");
const zix11 = @import("zix11");

const randr = zix11.ext.randr;

fn connectionName(conn: randr.Connection) []const u8 {
    return switch (conn) {
        .Connected => "connected",
        .Disconnected => "disconnected",
        .Unknown => "unknown",
        _ => "unknown",
    };
}

fn hasFlag(mask: u32, flag: randr.ModeFlag) bool {
    return (mask & @intFromEnum(flag)) != 0;
}

fn modeRefreshHz(mode: randr.ModeInfo) f64 {
    if (mode.dot_clock == 0 or mode.htotal == 0 or mode.vtotal == 0) return 0;

    var refresh = @as(f64, @floatFromInt(mode.dot_clock)) /
        @as(f64, @floatFromInt(mode.htotal)) /
        @as(f64, @floatFromInt(mode.vtotal));

    if (hasFlag(mode.mode_flags, .Interlace)) refresh *= 2;
    if (hasFlag(mode.mode_flags, .DoubleScan)) refresh /= 2;

    return refresh;
}

fn modeNameAt(resources: randr.GetScreenResourcesCurrentReply, mode_index: usize) []const u8 {
    var offset: usize = 0;
    for (resources.modes[0..mode_index]) |mode| {
        offset += mode.name_len;
    }
    return resources.names[offset .. offset + resources.modes[mode_index].name_len];
}

fn findModeIndex(resources: randr.GetScreenResourcesCurrentReply, mode: randr.Mode) ?usize {
    const mode_id = @intFromEnum(mode);
    for (resources.modes, 0..) |info, idx| {
        if (info.id == mode_id) return idx;
    }
    return null;
}

fn printCurrentMode(resources: randr.GetScreenResourcesCurrentReply, crtc_info: ?randr.GetCrtcInfoReply) void {
    const info = crtc_info orelse {
        std.debug.print("\n", .{});
        return;
    };
    if (@intFromEnum(info.mode) == 0) {
        std.debug.print("\n", .{});
        return;
    }
    const mode_index = findModeIndex(resources, info.mode) orelse {
        std.debug.print("\n", .{});
        return;
    };
    const mode = resources.modes[mode_index];
    std.debug.print(" {d}x{d}+{d}+{d}", .{ info.width, info.height, info.x, info.y });
    std.debug.print(" {s}", .{modeNameAt(resources, mode_index)});
    std.debug.print(" {d:.2}Hz", .{modeRefreshHz(mode)});
    std.debug.print("\n", .{});
}

fn printModes(
    resources: randr.GetScreenResourcesCurrentReply,
    output_info: randr.GetOutputInfoReply,
    crtc_info: ?randr.GetCrtcInfoReply,
) void {
    const active_mode = if (crtc_info) |info| @intFromEnum(info.mode) else 0;

    for (output_info.modes, 0..) |mode_id, idx| {
        const mode_index = findModeIndex(resources, mode_id) orelse continue;
        const mode = resources.modes[mode_index];
        std.debug.print("  {s} {d:.2}Hz", .{
            modeNameAt(resources, mode_index),
            modeRefreshHz(mode),
        });
        if (@intFromEnum(mode_id) == active_mode) {
            std.debug.print(" *", .{});
        }
        if (idx < output_info.num_preferred) {
            std.debug.print(" +", .{});
        }
        std.debug.print("\n", .{});
    }
}

fn loadCrtcInfo(
    conn: *zix11.Connection,
    allocator: std.mem.Allocator,
    config_timestamp: u32,
    crtc: randr.Crtc,
) !?randr.GetCrtcInfoReply {
    if (@intFromEnum(crtc) == 0) return null;
    return try conn.requestAlloc(allocator, randr.GetCrtcInfo, .{
        .crtc = crtc,
        .config_timestamp = config_timestamp,
    });
}

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    try conn.registerExtension(.RANDR);

    const version = try conn.request(randr.QueryVersion, .{
        .major_version = 1,
        .minor_version = 6,
    });

    std.debug.print("Screen 0: RANDR {}.{}\n", .{ version.major_version, version.minor_version });

    var resources = try conn.requestAlloc(init.gpa, randr.GetScreenResourcesCurrent, .{
        .window = conn.root_window,
    });
    defer resources.deinit(init.gpa);

    for (resources.outputs) |output| {
        var output_info = try conn.requestAlloc(init.gpa, randr.GetOutputInfo, .{
            .output = output,
            .config_timestamp = resources.config_timestamp,
        });
        defer output_info.deinit(init.gpa);

        var crtc_info = try loadCrtcInfo(&conn, init.gpa, resources.config_timestamp, output_info.crtc);
        defer if (crtc_info) |*info| info.deinit(init.gpa);

        std.debug.print("{s} {s}", .{
            output_info.name,
            connectionName(output_info.connection),
        });
        if (output_info.connection == .Connected) {
            printCurrentMode(resources, crtc_info);
            printModes(resources, output_info, crtc_info);
        } else {
            std.debug.print("\n", .{});
        }
    }
}
