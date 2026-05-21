const std = @import("std");
const builtin = @import("builtin");
const zix11 = @import("root.zig");
const x = zix11.x;

test {
    _ = zix11.ewmh;
    _ = @import("io.zig");
    _ = @import("protocol_test.zig");
    _ = @import("connection_test.zig");
    _ = @import("properties_test.zig");
}

test "InternAtom request encoding" {
    var buf: [32]u8 = undefined;
    var writer = zix11.io.FixedBufferWriter.init(&buf);
    const req = x.InternAtom{
        .only_if_exists = true,
        .name = "WM_NAME",
    };
    req.encode(&writer);
    const body = buf[0..writer.seek];

    try std.testing.expect(x.InternAtom.extension == null);
    try std.testing.expectEqual(@as(u8, 16), x.InternAtom.opcode);
    try std.testing.expectEqual(@as(u8, 1), req.headerByte1());
    try std.testing.expectEqual(@as(u16, 7), std.mem.readInt(u16, body[0..2], .native));
    try std.testing.expectEqualSlices(u8, "WM_NAME", body[4..11]);
}

test "SetupRequest encoding" {
    var buf: [64]u8 = undefined;
    var writer = zix11.io.FixedBufferWriter.init(&buf);
    (x.SetupRequest{
        .byte_order = switch (builtin.cpu.arch.endian()) {
            .little => 'l',
            .big => 'B',
        },
        .protocol_major_version = 11,
        .protocol_minor_version = 0,
        .authorization_protocol_name = "MIT-MAGIC-COOKIE-1",
        .authorization_protocol_data = &.{ 0xaa, 0xbb, 0xcc, 0xdd },
    }).encode(&writer);
    const packet = buf[0..writer.seek];

    try std.testing.expectEqual(switch (builtin.cpu.arch.endian()) {
        .little => @as(u8, 'l'),
        .big => @as(u8, 'B'),
    }, packet[0]);
    try std.testing.expectEqual(@as(u16, 11), std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(@as(u16, 18), std.mem.readInt(u16, packet[6..8], .native));
    try std.testing.expectEqual(@as(u16, 4), std.mem.readInt(u16, packet[8..10], .native));
    try std.testing.expectEqualSlices(u8, "MIT-MAGIC-COOKIE-1", packet[12..30]);
    try std.testing.expectEqualSlices(u8, &.{ 0xaa, 0xbb, 0xcc, 0xdd }, packet[32..36]);
}

test "GetProperty reply decode copies into caller scratch" {
    var packet = std.mem.zeroes([40]u8);
    packet[0] = 1;
    packet[1] = 32;
    std.mem.writeInt(u32, packet[4..8], 2, .native);
    std.mem.writeInt(u32, packet[8..12], 57, .native);
    std.mem.writeInt(u32, packet[16..20], 2, .native);
    const value = [_]u8{ 0xaa, 0xbb, 0xcc, 0xdd, 0x11, 0x22, 0x33, 0x44 };
    @memcpy(packet[32..40], value[0..]);
    var scratch: [8]u8 = undefined;
    var reader: std.Io.Reader = .fixed(&packet);
    const reply = try x.GetPropertyReply.decode(&scratch, &reader);

    try std.testing.expectEqual(@as(u8, 32), reply.format);
    try std.testing.expectEqual(@as(x.Atom, @enumFromInt(57)), reply.type);
    try std.testing.expectEqual(@as(u32, 2), reply.value_len);
    try std.testing.expectEqualSlices(u8, &.{ 0xaa, 0xbb, 0xcc, 0xdd, 0x11, 0x22, 0x33, 0x44 }, reply.value);
}

test "Event.toBytes" {
    const event: x.ClientMessageEvent = .{
        .window = @enumFromInt(0),
        .type = @enumFromInt(0),
        .format = 32,
        .data = zix11.events.clientMessageData(u32, &.{ 10, 20 }),
    };
    const bytes = event.toBytes();
    _ = bytes;
    var expected: [8]u8 = undefined;
    std.mem.writeInt(u32, expected[0..4], 10, .native);
    std.mem.writeInt(u32, expected[4..8], 20, .native);
    const actual = try event.data.asData8();
    try std.testing.expectEqualSlices(u8, &expected, actual[0..8]);
}

test "ConfigureWindow" {
    var buf: [64]u8 = undefined;
    var writer = zix11.io.FixedBufferWriter.init(&buf);
    const cw: x.ConfigureWindow = .{ .window = x.Window.None, .value_list = .{} };
    cw.encode(&writer);
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
