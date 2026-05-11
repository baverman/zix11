const std = @import("std");
const zix = @import("zix");

pub fn main(init: std.process.Init) !void {
    var conn = try zix.Connection.connectFromInit(init, init.gpa);
    defer conn.deinit();

    std.debug.print("root window: 0x{x}\n", .{@intFromEnum(conn.root_window)});

    const atom_window = (try conn.request(zix.xproto.InternAtomRequest{
        .only_if_exists = false,
        .name = "WINDOW",
    })).atom;
    const atom_active = (try conn.request(zix.xproto.InternAtomRequest{
        .only_if_exists = false,
        .name = "_NET_ACTIVE_WINDOW",
    })).atom;
    const atom_client_list = (try conn.request(zix.xproto.InternAtomRequest{
        .only_if_exists = false,
        .name = "_NET_CLIENT_LIST",
    })).atom;

    var scratch: [16 * 1024]u8 align(4) = undefined;

    const active_windows = try zix.getProperty(&conn, conn.root_window, atom_active, atom_window, zix.xproto.Window, &scratch);
    if (active_windows.len > 0) {
        std.debug.print("_NET_ACTIVE_WINDOW: 0x{x}\n", .{@intFromEnum(active_windows[0])});
    } else {
        std.debug.print("_NET_ACTIVE_WINDOW: <empty>\n", .{});
    }

    const client_windows = try zix.getProperty(&conn, conn.root_window, atom_client_list, atom_window, zix.xproto.Window, &scratch);
    std.debug.print("_NET_CLIENT_LIST count: {}\n", .{client_windows.len});
    for (client_windows) |window| {
        std.debug.print("  0x{x}\n", .{@intFromEnum(window)});
    }

    const window = try conn.allocId(zix.xproto.Window);

    try conn.request(zix.xproto.CreateWindowRequest{
        .depth = 0,
        .wid = window,
        .parent = conn.root_window,
        .x = 100,
        .y = 100,
        .width = 320,
        .height = 200,
        .border_width = 0,
        .class = @intCast(@intFromEnum(zix.xproto.WindowClass.CopyFromParent)),
        .visual = 0,
        .value_list = .{
            .background_pixel = 0x00ff0000,
            .event_mask = zix.xproto.EventMask.of(&.{ .Exposure, .ButtonPress }),
        },
    });
    try conn.request(zix.xproto.MapWindowRequest{ .window = window });
    std.debug.print("created window: 0x{x}\n", .{@intFromEnum(window)});

    while (true) {
        const event = try conn.nextEvent();
        switch (event) {
            .expose => |ev| {
                if (ev.window == window and ev.count == 0) {
                    std.debug.print("expose {}x{}\n", .{ ev.width, ev.height });
                }
            },
            .button_press => |ev| {
                if (ev.event == window) {
                    std.debug.print("button press at {}, {}\n", .{ ev.event_x, ev.event_y });
                    break;
                }
            },
            else => {},
        }
    }
}
