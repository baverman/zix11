const std = @import("std");
const zix = @import("zix");

pub fn main(init: std.process.Init) !void {
    var conn = try zix.Connection.connectFromInit(init, init.gpa);
    defer conn.deinit();

    std.debug.print("root window: 0x{x}\n", .{conn.root_window});

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

    var scratch: [16 * 1024]u8 = undefined;

    const active = try conn.requestBuf(zix.xproto.GetPropertyRequest{
        .delete_value = false,
        .window = conn.root_window,
        .property = atom_active,
        .type_atom = atom_window,
        .long_offset = 0,
        .long_length = 4096,
    }, &scratch);
    const active_windows = try propertyU32s(active);
    if (active_windows.len > 0) {
        std.debug.print("_NET_ACTIVE_WINDOW: 0x{x}\n", .{active_windows[0]});
    } else {
        std.debug.print("_NET_ACTIVE_WINDOW: <empty>\n", .{});
    }

    const clients = try conn.requestBuf(zix.xproto.GetPropertyRequest{
        .delete_value = false,
        .window = conn.root_window,
        .property = atom_client_list,
        .type_atom = atom_window,
        .long_offset = 0,
        .long_length = 4096,
    }, &scratch);
    const client_windows = try propertyU32s(clients);
    std.debug.print("_NET_CLIENT_LIST count: {}\n", .{client_windows.len});
    for (client_windows) |window| {
        std.debug.print("  0x{x}\n", .{window});
    }
}

fn propertyU32s(reply: zix.xproto.GetPropertyReply) ![]align(1) const u32 {
    if (reply.format != 32) return error.UnexpectedFormat;
    if (reply.value_len * 4 > reply.value.len) return error.MalformedProperty;
    if (reply.bytes_after != 0) return error.PropertyTruncated;
    return std.mem.bytesAsSlice(u32, reply.value[0 .. reply.value_len * 4]);
}
