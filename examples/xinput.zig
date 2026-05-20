const std = @import("std");
const zix11 = @import("zix11");

const xinput = zix11.ext.xinput;

fn deviceTypeName(kind: xinput.DeviceType) []const u8 {
    return switch (kind) {
        .MasterPointer => "master pointer",
        .MasterKeyboard => "master keyboard",
        .SlavePointer => "slave pointer",
        .SlaveKeyboard => "slave keyboard",
        .FloatingSlave => "floating slave",
        _ => "unknown",
    };
}

fn valuatorModeName(mode: xinput.ValuatorMode) []const u8 {
    return switch (mode) {
        .Absolute => "absolute",
        .Relative => "relative",
        _ => "unknown",
    };
}

fn scrollTypeName(kind: xinput.ScrollType) []const u8 {
    return switch (kind) {
        .Vertical => "vertical",
        .Horizontal => "horizontal",
        _ => "unknown",
    };
}

fn touchModeName(mode: xinput.TouchMode) []const u8 {
    return switch (mode) {
        .Direct => "direct",
        .Dependent => "dependent",
        _ => "unknown",
    };
}

fn printClass(info: xinput.DeviceClass) void {
    switch (info.data) {
        .key => |data| {
            std.debug.print("  key: {} keys\n", .{data.num_keys});
        },
        .button => |data| {
            std.debug.print("  button: {} buttons\n", .{data.num_buttons});
        },
        .valuator => |data| {
            std.debug.print("  valuator {}: {s} {s} res={}\n", .{
                data.number,
                valuatorModeName(data.mode),
                if (@intFromEnum(data.label) == 0) "(no label)" else "(labeled)",
                data.resolution,
            });
        },
        .scroll => |data| {
            std.debug.print("  scroll {}: {s} flags=0x{x}\n", .{
                data.number,
                scrollTypeName(data.scroll_type),
                data.flags,
            });
        },
        .touch => |data| {
            std.debug.print("  touch: {s} touches={}\n", .{
                touchModeName(data.mode),
                data.num_touches,
            });
        },
        .gesture => |data| {
            std.debug.print("  gesture: touches={}\n", .{data.num_touches});
        },
    }
}

fn printDevice(info: xinput.XIDeviceInfo) void {
    std.debug.print("{}: {s} [{s}] enabled={} attachment={}\n", .{
        info.deviceid,
        info.name,
        deviceTypeName(info.type),
        info.enabled,
        info.attachment,
    });
    for (info.classes) |class_info| {
        printClass(class_info);
    }
}

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    try conn.registerExtension(.XINPUT);

    const version = try conn.request(xinput.XIQueryVersion, .{
        .major_version = 2,
        .minor_version = 4,
    });
    std.debug.print("XInput version {}.{}\n", .{
        version.major_version,
        version.minor_version,
    });

    var devices = try conn.requestAlloc(init.gpa, xinput.XIQueryDevice, .{
        .deviceid = @intCast(@intFromEnum(xinput.Device.All)),
    });
    defer devices.deinit(init.gpa);

    for (devices.infos) |info| {
        printDevice(info);
    }
}
