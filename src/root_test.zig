const std = @import("std");
const zix11 = @import("root.zig");
const xproto = zix11.xproto;

test {
    _ = zix11.ewmh;
    _ = @import("connection_test.zig");
}

test "InternAtom request encoding" {
    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = xproto.InternAtom{
        .only_if_exists = true,
        .name = "WM_NAME",
    };
    try req.encode(&writer);
    const body = buf[0..writer.end];

    try std.testing.expect(xproto.InternAtom.extension == null);
    try std.testing.expectEqual(@as(u8, 16), xproto.InternAtom.opcode);
    try std.testing.expectEqual(@as(u8, 1), req.headerByte1());
    try std.testing.expectEqual(@as(usize, req.byteLen()), body.len);
    try std.testing.expectEqual(@as(u16, 7), std.mem.readInt(u16, body[0..2], .little));
    try std.testing.expectEqualSlices(u8, "WM_NAME", body[4..11]);
}

test "SetupRequest encoding" {
    var buf: [64]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    try (xproto.SetupRequest{
        .byte_order = 'l',
        .protocol_major_version = 11,
        .protocol_minor_version = 0,
        .authorization_protocol_name = "MIT-MAGIC-COOKIE-1",
        .authorization_protocol_data = &.{ 0xaa, 0xbb, 0xcc, 0xdd },
    }).encode(&writer);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(u8, 'l'), packet[0]);
    try std.testing.expectEqual(@as(u16, 11), std.mem.readInt(u16, packet[2..4], .little));
    try std.testing.expectEqual(@as(u16, 18), std.mem.readInt(u16, packet[6..8], .little));
    try std.testing.expectEqual(@as(u16, 4), std.mem.readInt(u16, packet[8..10], .little));
    try std.testing.expectEqualSlices(u8, "MIT-MAGIC-COOKIE-1", packet[12..30]);
    try std.testing.expectEqualSlices(u8, &.{ 0xaa, 0xbb, 0xcc, 0xdd }, packet[32..36]);
}

test "GetProperty reply decode copies into caller scratch" {
    const packet = [_]u8{
        1,    32,   0,    0,
        2,    0,    0,    0,
        57,   0,    0,    0,
        0,    0,    0,    0,
        2,    0,    0,    0,
        0,    0,    0,    0,
        0,    0,    0,    0,
        0,    0,    0,    0,
        0xaa, 0xbb, 0xcc, 0xdd,
        0x11, 0x22, 0x33, 0x44,
    };
    var scratch: [8]u8 = undefined;
    var reader: std.Io.Reader = .fixed(&packet);
    const reply = try xproto.GetPropertyReply.decode(&scratch, &reader);

    try std.testing.expectEqual(@as(u8, 32), reply.format);
    try std.testing.expectEqual(@as(xproto.Atom, @enumFromInt(57)), reply.type);
    try std.testing.expectEqual(@as(u32, 2), reply.value_len);
    try std.testing.expectEqualSlices(u8, &.{ 0xaa, 0xbb, 0xcc, 0xdd, 0x11, 0x22, 0x33, 0x44 }, reply.value);
}

test "Event.toBytes" {
    const event: xproto.ClientMessageEvent = .{
        .window = @enumFromInt(0),
        .type = @enumFromInt(0),
        .format = 32,
        .data = zix11.clientMessageData(u32, &.{ 10, 20 }),
    };
    const bytes = try event.toBytes();
    _ = bytes;
    try std.testing.expectEqualSlices(u8, &.{ 10, 0, 0, 0, 20, 0, 0, 0 }, event.data.data8[0..8]);
}

test "ConfigureWindow" {
    var buf: [64]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const cw: xproto.ConfigureWindow = .{ .window = xproto.Window.None, .value_list = .{} };
    try cw.encode(&writer);
}

// const T1 = enum(u32) { Window = 0 };
// const T2 = enum(u32) { Pict = 0 };
// const TU = enum { Window, Pict, };
//
// fn decode(comptime T: type, value: u32) ?TU {
//     const tag = std.enums.fromInt(T, value) orelse return null;
//     const name = @tagName(tag);
//     std.debug.print("@@ {any}\n", .{@field(TU, name)});
//     return null;
// }
//
// test "boo" {
//     try std.testing.expectEqual(TU.Window, decode(T1, 0));
//     try std.testing.expectEqual(TU.Pict, decode(T2, 0));
// }
