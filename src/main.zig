const std = @import("std");
const zix = @import("zix");

pub fn main(init: std.process.Init) !void {
    var conn = try zix.Connection.connectFromInit(init, init.gpa);
    defer conn.deinit();

    std.debug.print("root window: 0x{x}\n", .{conn.root_window});

    const atom_window = try zix.xproto.internAtom(&conn, "WINDOW");
    const atom_active = try zix.xproto.internAtom(&conn, "_NET_ACTIVE_WINDOW");
    const atom_client_list = try zix.xproto.internAtom(&conn, "_NET_CLIENT_LIST");

    var scratch: [16 * 1024]u8 = undefined;

    const active = try zix.xproto.getProperty(&conn, conn.root_window, atom_active, atom_window, &scratch);
    const active_windows = try active.u32s();
    if (active_windows.len > 0) {
        std.debug.print("_NET_ACTIVE_WINDOW: 0x{x}\n", .{active_windows[0]});
    } else {
        std.debug.print("_NET_ACTIVE_WINDOW: <empty>\n", .{});
    }

    const clients = try zix.xproto.getProperty(&conn, conn.root_window, atom_client_list, atom_window, &scratch);
    const client_windows = try clients.u32s();
    std.debug.print("_NET_CLIENT_LIST count: {}\n", .{client_windows.len});
    for (client_windows) |window| {
        std.debug.print("  0x{x}\n", .{window});
    }
}
