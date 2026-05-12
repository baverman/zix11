const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.xproto;

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromInit(init, init.gpa);
    defer conn.deinit();

    std.debug.print("root window: 0x{x}\n", .{@intFromEnum(conn.root_window)});

    const atom_window = (try conn.request(x.InternAtom, .{
        .only_if_exists = false,
        .name = "WINDOW",
    })).atom;
    const atom_active = (try conn.request(x.InternAtom, .{
        .only_if_exists = false,
        .name = "_NET_ACTIVE_WINDOW",
    })).atom;
    const atom_client_list = (try conn.request(x.InternAtom, .{
        .only_if_exists = false,
        .name = "_NET_CLIENT_LIST",
    })).atom;

    var scratch: [16 * 1024]u8 align(4) = undefined;

    const active_windows = try zix11.getProperty(&conn, conn.root_window, atom_active, atom_window, x.Window, &scratch);
    if (active_windows.len > 0) {
        std.debug.print("_NET_ACTIVE_WINDOW: 0x{x}\n", .{@intFromEnum(active_windows[0])});
    } else {
        std.debug.print("_NET_ACTIVE_WINDOW: <empty>\n", .{});
    }

    const client_windows = try zix11.getProperty(&conn, conn.root_window, atom_client_list, atom_window, x.Window, &scratch);
    std.debug.print("_NET_CLIENT_LIST count: {}\n", .{client_windows.len});
    for (client_windows) |window| {
        std.debug.print("  0x{x}\n", .{@intFromEnum(window)});
    }

    const window = try conn.allocId(x.Window);

    try conn.request(x.CreateWindow, .{
        .depth = 0,
        .wid = window,
        .parent = conn.root_window,
        .x = 100,
        .y = 100,
        .width = 320,
        .height = 200,
        .border_width = 0,
        .class = .CopyFromParent,
        .visual = 0,
        .value_list = .{
            .background_pixel = 0x00ff0000,
            .event_mask = x.EventMask.of(&.{ .Exposure, .ButtonPress }),
        },
    });

    conn.request(x.MapWindow, .{ .window = @enumFromInt(0xbadbad) }) catch |err| switch (err) {
        error.X11ProtocolError => {
            const e = conn.lastError();
            switch (e.code) {
                .Window => {
                    std.debug.print("BadWidnow: 0x{x}\n", .{e.bad_value});
                },
                else => return err,
            }
        },
        else => return err,
    };

    try conn.request(x.MapWindow, .{ .window = window });
    std.debug.print("created window: 0x{x}\n", .{@intFromEnum(window)});

    while (true) {
        const event = try conn.nextEvent();
        switch (event) {
            .Expose => |ev| {
                if (ev.window == window and ev.count == 0) {
                    std.debug.print("expose {}x{}\n", .{ ev.width, ev.height });
                }
            },
            .ButtonPress => |ev| {
                if (ev.event == window) {
                    std.debug.print("button press at {}, {}\n", .{ ev.event_x, ev.event_y });
                    break;
                }
            },
            else => {},
        }
    }
}
