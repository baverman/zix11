const std = @import("std");
const connection = @import("connection.zig");
const properties = @import("properties.zig");
const protocol = @import("protocol.zig");
const x = @import("gen/xproto.zig");
const makeConn = @import("test_helpers.zig").makeConn;

fn focusReplyPacket(sequence: u16) [32]u8 {
    var packet = std.mem.zeroes([32]u8);
    packet[0] = 1;
    std.mem.writeInt(u16, packet[2..4], sequence, .native);
    return packet;
}

test "properties.set uses CARDINAL for scalar u32" {
    const reply = focusReplyPacket(2);
    var write_buf: [64]u8 = undefined;
    var conn = try makeConn(&reply, &write_buf);
    defer conn.deinit();

    try properties.set(&conn, @enumFromInt(0x11), @enumFromInt(0x22), @as(u32, 7));

    const written = conn.transport.writer().buffered();
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
    const reply = focusReplyPacket(2);
    var write_buf: [96]u8 = undefined;
    var conn = try makeConn(&reply, &write_buf);
    defer conn.deinit();

    const windows = [_]x.Window{ @enumFromInt(0xaa), @enumFromInt(0xbb) };
    try properties.set(&conn, @enumFromInt(0x11), @enumFromInt(0x22), &windows);

    const written = conn.transport.writer().buffered();
    try std.testing.expectEqual(@as(u8, x.ChangeProperty.opcode), written[0]);
    try std.testing.expectEqual(@as(u32, @intFromEnum(x.Atom.WINDOW)), std.mem.readInt(u32, written[12..16], .native));
    try std.testing.expectEqual(@as(u8, 32), written[16]);
    try std.testing.expectEqual(@as(u32, 2), std.mem.readInt(u32, written[20..24], .native));
    try std.testing.expectEqual(@as(u32, 0xaa), std.mem.readInt(u32, written[24..28], .native));
    try std.testing.expectEqual(@as(u32, 0xbb), std.mem.readInt(u32, written[28..32], .native));
}

test "properties.setAs uses explicit UTF8_STRING for string slice" {
    const reply = focusReplyPacket(2);
    var write_buf: [96]u8 = undefined;
    var conn = try makeConn(&reply, &write_buf);
    defer conn.deinit();

    try properties.setAs(&conn, @enumFromInt(0x11), @enumFromInt(0x22), @enumFromInt(0x33), "Hi");

    const written = conn.transport.writer().buffered();
    try std.testing.expectEqual(@as(u8, x.ChangeProperty.opcode), written[0]);
    try std.testing.expectEqual(@as(u32, 0x33), std.mem.readInt(u32, written[12..16], .native));
    try std.testing.expectEqual(@as(u8, 8), written[16]);
    try std.testing.expectEqual(@as(u32, 2), std.mem.readInt(u32, written[20..24], .native));
    try std.testing.expectEqualSlices(u8, "Hi", written[24..26]);
}

test "properties.setAs uses explicit atom for scalar" {
    const reply = focusReplyPacket(2);
    var write_buf: [64]u8 = undefined;
    var conn = try makeConn(&reply, &write_buf);
    defer conn.deinit();

    try properties.setAs(&conn, @enumFromInt(0x11), @enumFromInt(0x22), @enumFromInt(0x44), @as(u32, 9));

    const written = conn.transport.writer().buffered();
    try std.testing.expectEqual(@as(u32, 0x44), std.mem.readInt(u32, written[12..16], .native));
    try std.testing.expectEqual(@as(u32, 9), std.mem.readInt(u32, written[24..28], .native));
}
