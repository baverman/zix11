const std = @import("std");
const connection = @import("connection.zig");
const properties = @import("properties.zig");
const protocol = @import("protocol.zig");
const x = @import("gen/xproto.zig");

fn makeConn(
    proto: *protocol.Protocol,
    transport: *connection.StreamTransport,
    reply_bytes: []const u8,
    write_buf: []u8,
) connection.Connection {
    var dummy_read_buf: [1]u8 = undefined;
    var dummy_write_buf: [1]u8 = undefined;

    transport.* = .{
        .io = std.testing.io,
        .stream = undefined,
        .read_buffer = &dummy_read_buf,
        .write_buffer = &dummy_write_buf,
        .stream_reader = .{
            .io = std.testing.io,
            .interface = .fixed(reply_bytes),
            .stream = undefined,
            .err = null,
        },
        .stream_writer = .{
            .io = std.testing.io,
            .interface = .fixed(write_buf),
            .stream = undefined,
            .err = null,
            .write_file_err = null,
        },
    };

    return .{
        .allocator = std.testing.allocator,
        .proto = proto,
        .transport = transport,
        .root_window = @enumFromInt(0),
    };
}

fn focusReplyPacket(sequence: u16) [32]u8 {
    var packet = std.mem.zeroes([32]u8);
    packet[0] = 1;
    std.mem.writeInt(u16, packet[2..4], sequence, .native);
    return packet;
}

test "properties.set uses CARDINAL for scalar u32" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    const reply = focusReplyPacket(2);
    var write_buf: [64]u8 = undefined;
    var transport: connection.StreamTransport = undefined;
    var conn = makeConn(&proto, &transport, &reply, &write_buf);

    try properties.set(&conn, @enumFromInt(0x11), @enumFromInt(0x22), @as(u32, 7));

    const written = write_buf[0..transport.stream_writer.interface.end];
    try std.testing.expectEqual(@as(u8, x.ChangeProperty.opcode), written[0]);
    try std.testing.expectEqual(@as(u8, @intFromEnum(x.PropMode.Replace)), written[1]);
    try std.testing.expectEqual(@as(u16, 7), std.mem.readInt(u16, written[2..4], .native));
    try std.testing.expectEqual(@as(u32, 0x11), std.mem.readInt(u32, written[4..8], .native));
    try std.testing.expectEqual(@as(u32, 0x22), std.mem.readInt(u32, written[8..12], .native));
    try std.testing.expectEqual(@as(u32, @intFromEnum(x.Atom.CARDINAL)), std.mem.readInt(u32, written[12..16], .native));
    try std.testing.expectEqual(@as(u8, 32), written[16]);
    try std.testing.expectEqual(@as(u32, 1), std.mem.readInt(u32, written[20..24], .native));
    try std.testing.expectEqual(@as(u32, 7), std.mem.readInt(u32, written[24..28], .native));
    try std.testing.expectEqual(@as(u8, x.GetInputFocus.opcode), written[28]);
}

test "properties.set uses WINDOW for array pointer slice" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    const reply = focusReplyPacket(2);
    var write_buf: [96]u8 = undefined;
    var transport: connection.StreamTransport = undefined;
    var conn = makeConn(&proto, &transport, &reply, &write_buf);

    const windows = [_]x.Window{ @enumFromInt(0xaa), @enumFromInt(0xbb) };
    try properties.set(&conn, @enumFromInt(0x11), @enumFromInt(0x22), &windows);

    const written = write_buf[0..transport.stream_writer.interface.end];
    try std.testing.expectEqual(@as(u8, x.ChangeProperty.opcode), written[0]);
    try std.testing.expectEqual(@as(u32, @intFromEnum(x.Atom.WINDOW)), std.mem.readInt(u32, written[12..16], .native));
    try std.testing.expectEqual(@as(u8, 32), written[16]);
    try std.testing.expectEqual(@as(u32, 2), std.mem.readInt(u32, written[20..24], .native));
    try std.testing.expectEqual(@as(u32, 0xaa), std.mem.readInt(u32, written[24..28], .native));
    try std.testing.expectEqual(@as(u32, 0xbb), std.mem.readInt(u32, written[28..32], .native));
}

test "properties.setAs uses explicit UTF8_STRING for string slice" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    const reply = focusReplyPacket(2);
    var write_buf: [96]u8 = undefined;
    var transport: connection.StreamTransport = undefined;
    var conn = makeConn(&proto, &transport, &reply, &write_buf);

    try properties.setAs(&conn, @enumFromInt(0x11), @enumFromInt(0x22), @enumFromInt(0x33), "Hi");

    const written = write_buf[0..transport.stream_writer.interface.end];
    try std.testing.expectEqual(@as(u8, x.ChangeProperty.opcode), written[0]);
    try std.testing.expectEqual(@as(u32, 0x33), std.mem.readInt(u32, written[12..16], .native));
    try std.testing.expectEqual(@as(u8, 8), written[16]);
    try std.testing.expectEqual(@as(u32, 2), std.mem.readInt(u32, written[20..24], .native));
    try std.testing.expectEqualSlices(u8, "Hi", written[24..26]);
}

test "properties.setAs uses explicit atom for scalar" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    const reply = focusReplyPacket(2);
    var write_buf: [64]u8 = undefined;
    var transport: connection.StreamTransport = undefined;
    var conn = makeConn(&proto, &transport, &reply, &write_buf);

    try properties.setAs(&conn, @enumFromInt(0x11), @enumFromInt(0x22), @enumFromInt(0x44), @as(u32, 9));

    const written = write_buf[0..transport.stream_writer.interface.end];
    try std.testing.expectEqual(@as(u32, 0x44), std.mem.readInt(u32, written[12..16], .native));
    try std.testing.expectEqual(@as(u32, 9), std.mem.readInt(u32, written[24..28], .native));
}
