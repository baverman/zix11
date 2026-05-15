const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.xproto;

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
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

    var window_buf: [128]x.Window = undefined;
    const active_windows = try zix11.getProperty(&conn, conn.root_window, atom_active, atom_window, x.Window, &window_buf);
    if (active_windows.len > 0) {
        std.debug.print("_NET_ACTIVE_WINDOW: 0x{x}\n", .{@intFromEnum(active_windows[0])});
    } else {
        std.debug.print("_NET_ACTIVE_WINDOW: <empty>\n", .{});
    }

    const client_windows = try zix11.getProperty(&conn, conn.root_window, atom_client_list, atom_window, x.Window, &window_buf);
    std.debug.print("_NET_CLIENT_LIST count: {}\n", .{client_windows.len});
    for (client_windows) |window| {
        std.debug.print("  0x{x}\n", .{@intFromEnum(window)});
    }
}
