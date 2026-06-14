const std = @import("std");
const zix11 = @import("../root.zig");

pub fn makeConn(reply_bytes: []const u8, write_buf: []u8) !zix11.Connection {
    var conn: zix11.Connection = try .init(std.testing.allocator, std.testing.io);
    conn.transport.stream_reader = .{
        .io = std.testing.io,
        .interface = .fixed(reply_bytes),
        .stream = undefined,
        .err = null,
    };

    conn.transport.stream_writer = .{
        .io = std.testing.io,
        .interface = .fixed(write_buf),
        .stream = undefined,
        .err = null,
        .write_file_err = null,
    };
    return conn;
}
