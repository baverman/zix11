const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.xproto;

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    std.debug.print("root window: 0x{x}\n", .{@intFromEnum(conn.root_window)});

    const atom_active = try zix11.internAtom(&conn, "_NET_ACTIVE_WINDOW", false);
    const atom_client_list = try zix11.internAtom(&conn, "_NET_CLIENT_LIST", false);

    const active_window = try zix11.getScalarProperty(&conn, conn.root_window, atom_active, zix11.PropertyType.window);
    if (active_window) |aw| {
        std.debug.print("_NET_ACTIVE_WINDOW: 0x{x}\n", .{@intFromEnum(aw)});
    } else {
        std.debug.print("_NET_ACTIVE_WINDOW: <empty>\n", .{});
    }

    var window_buf: [128]x.Window = undefined;
    const client_windows = try zix11.getProperty(&conn, conn.root_window, atom_client_list, zix11.PropertyType.window, &window_buf);
    std.debug.print("_NET_CLIENT_LIST count: {}\n", .{client_windows.len});
    for (client_windows) |window| {
        std.debug.print("  0x{x}\n", .{@intFromEnum(window)});
    }
}
