const std = @import("std");
const zix11 = @import("zix11");

const dpms = zix11.ext.dpms;

fn modeName(mode: dpms.DPMSMode) []const u8 {
    return switch (mode) {
        .On => "on",
        .Standby => "standby",
        .Suspend => "suspend",
        .Off => "off",
        _ => "unknown",
    };
}

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    try conn.registerExtension(.DPMS);

    const version = try conn.request(dpms.GetVersion, .{
        .client_major_version = 1,
        .client_minor_version = 1,
    });
    std.debug.print("DPMS version {}.{}\n", .{
        version.server_major_version,
        version.server_minor_version,
    });

    const capable = try conn.request(dpms.Capable, .{});
    std.debug.print("capable: {}\n", .{capable.capable});
    if (!capable.capable) return;

    const timeouts = try conn.request(dpms.GetTimeouts, .{});
    std.debug.print("timeouts: standby={} suspend={} off={}\n", .{
        timeouts.standby_timeout,
        timeouts.suspend_timeout,
        timeouts.off_timeout,
    });

    const info = try conn.request(dpms.Info, .{});
    std.debug.print("state: enabled={} level={s}\n", .{
        info.state,
        modeName(info.power_level),
    });

    std.debug.print("sleeping 1s before forcing off\n", .{});
    try init.io.sleep(std.Io.Duration.fromSeconds(1), .awake);

    try conn.request(dpms.ForceLevel, .{ .power_level = .Off });
    std.debug.print("forced dpms off\n", .{});
}
