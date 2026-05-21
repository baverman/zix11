const std = @import("std");
const zix11 = @import("zix11");

const x = zix11.x;
const xinput = zix11.ext.xinput;
const Atoms = zix11.atoms.AtomStruct(enum {
    WM_PROTOCOLS,
    WM_DELETE_WINDOW,
    UTF8_STRING,
    _NET_WM_NAME,
});

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    try conn.registerExtension(.XINPUT);
    const atom = try zix11.atoms.getAll(Atoms, &conn);

    const version = try conn.request(xinput.XIQueryVersion, .{
        .major_version = 2,
        .minor_version = 4,
    });
    std.debug.print("XInput version {}.{}\n", .{
        version.major_version,
        version.minor_version,
    });

    const window = try conn.allocId(x.Window);
    try conn.request(x.CreateWindow, .{
        .depth = 0,
        .wid = window,
        .parent = conn.root_window,
        .x = 100,
        .y = 100,
        .width = 640,
        .height = 360,
        .border_width = 0,
        .class = .CopyFromParent,
        .visual = 0,
        .value_list = .{
            .background_pixel = 0x00202020,
            .event_mask = x.EventMask.of(&.{ .Exposure, .StructureNotify }),
        },
    });

    try zix11.properties.setAs(
        &conn,
        window,
        atom._NET_WM_NAME,
        atom.UTF8_STRING,
        "XInput2 Demo",
    );
    const wm_delete_payload = [_]u32{@intFromEnum(atom.WM_DELETE_WINDOW)};
    try zix11.properties.setAs(
        &conn,
        window,
        atom.WM_PROTOCOLS,
        x.Atom.ATOM,
        wm_delete_payload[0..],
    );

    const xi2_mask = [_]u32{
        @intFromEnum(xinput.XIEventMask.KeyPress) |
            @intFromEnum(xinput.XIEventMask.KeyRelease) |
            @intFromEnum(xinput.XIEventMask.Motion) |
            @intFromEnum(xinput.XIEventMask.FocusIn) |
            @intFromEnum(xinput.XIEventMask.FocusOut),
    };
    const xi2_masks = [_]xinput.EventMask{.{
        .deviceid = @intCast(@intFromEnum(xinput.Device.AllMaster)),
        .mask = &xi2_mask,
    }};

    conn.request(xinput.XISelectEvents, .{
        .window = window,
        .masks = &xi2_masks,
    }) catch |err| {
        std.debug.print("XISelectEvents failed: {any}\n", .{conn.lastError(err)});
        return err;
    };

    try conn.request(x.MapWindow, .{ .window = window });

    std.debug.print("window=0x{x} XI2 keyboard+motion on all master devices\n", .{
        @intFromEnum(window),
    });

    while (true) {
        while (try conn.pollEvent()) |event| {
            switch (event) {
                .Expose => |ev| {
                    if (ev.window == window and ev.count == 0) {
                        std.debug.print("expose {}x{}\n", .{ ev.width, ev.height });
                    }
                },
                .XInputFocusIn => |ev| {
                    std.debug.print("XI2 focus in: event=0x{x} child=0x{x} device={} source={}\n", .{
                        @intFromEnum(ev.event),
                        @intFromEnum(ev.child),
                        ev.deviceid,
                        ev.sourceid,
                    });
                },
                .XInputFocusOut => |ev| {
                    std.debug.print("XI2 focus out: event=0x{x} child=0x{x} device={} source={}\n", .{
                        @intFromEnum(ev.event),
                        @intFromEnum(ev.child),
                        ev.deviceid,
                        ev.sourceid,
                    });
                },
                .XInputKeyPress => |ev| {
                    std.debug.print("XI2 key press: event=0x{x} child=0x{x} keycode={} device={} source={} mods=0x{x}\n", .{
                        @intFromEnum(ev.event),
                        @intFromEnum(ev.child),
                        ev.detail,
                        ev.deviceid,
                        ev.sourceid,
                        ev.mods.effective,
                    });
                    if (ev.detail == 9) return;
                },
                .XInputKeyRelease => |ev| {
                    std.debug.print("XI2 key release: event=0x{x} child=0x{x} keycode={} device={} source={} mods=0x{x}\n", .{
                        @intFromEnum(ev.event),
                        @intFromEnum(ev.child),
                        ev.detail,
                        ev.deviceid,
                        ev.sourceid,
                        ev.mods.effective,
                    });
                },
                .XInputMotion => |ev| {
                    var body = try ev.getBody(init.gpa);
                    defer body.deinit(init.gpa);
                    std.debug.print("XI2 motion: event=0x{x} child=0x{x} device={} source={} x={} y={} values={}\n", .{
                        @intFromEnum(ev.event),
                        @intFromEnum(ev.child),
                        ev.deviceid,
                        ev.sourceid,
                        ev.event_x,
                        ev.event_y,
                        body.axisvalues.len,
                    });
                },
                .ClientMessage => |ev| {
                    if (ev.window == window and ev.type == atom.WM_PROTOCOLS) {
                        const data = try ev.data.asData32();
                        if (data[0] == @intFromEnum(atom.WM_DELETE_WINDOW)) return;
                    }
                },
                else => {},
            }
        }

        _ = try conn.waitForEvents(3000);
    }
}
