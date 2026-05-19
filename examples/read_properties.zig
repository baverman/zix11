const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.x;

// Declare app wide atoms
const Atoms = zix11.atoms.AtomStruct(enum {
    _NET_ACTIVE_WINDOW,
    _NET_CLIENT_LIST,
});

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    std.debug.print("root window: 0x{x}\n", .{@intFromEnum(conn.root_window)});

    // Fill atom values
    const atom = try zix11.atoms.getAll(Atoms, &conn);

    const active_window = try zix11.properties.getScalar(
        &conn,
        conn.root_window,
        atom._NET_ACTIVE_WINDOW,
        zix11.properties.Type.window,
    );
    if (active_window) |aw| {
        std.debug.print("_NET_ACTIVE_WINDOW: 0x{x}\n", .{@intFromEnum(aw)});
    } else {
        std.debug.print("_NET_ACTIVE_WINDOW: <empty>\n", .{});
    }

    var window_buf: [128]x.Window = undefined;
    const client_windows = try zix11.properties.get(
        &conn,
        conn.root_window,
        atom._NET_CLIENT_LIST,
        zix11.properties.Type.window,
        &window_buf,
    );
    std.debug.print("_NET_CLIENT_LIST count: {}\n", .{client_windows.len});
    for (client_windows) |window| {
        std.debug.print("  0x{x}\n", .{@intFromEnum(window)});
    }
}
