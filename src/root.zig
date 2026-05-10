const std = @import("std");

pub const wire = @import("wire.zig");
pub const xproto = @import("xproto.zig");
pub const Connection = @import("connection.zig").Connection;

test "InternAtom request encoding" {
    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    try (xproto.InternAtomRequest{
        .only_if_exists = true,
        .name = "WM_NAME",
    }).encode(&writer);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(usize, 16), packet.len);
    try std.testing.expectEqual(@as(u8, 16), packet[0]);
    try std.testing.expectEqual(@as(u8, 1), packet[1]);
    try std.testing.expectEqual(@as(u16, 4), std.mem.readInt(u16, packet[2..4], .little));
    try std.testing.expectEqualSlices(u8, "WM_NAME", packet[8..15]);
    try std.testing.expectEqual(@as(u8, 0), packet[15]);
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
        1, 32, 0, 0,
        2, 0, 0, 0,
        57, 0, 0, 0,
        0, 0, 0, 0,
        2, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0xaa, 0xbb, 0xcc, 0xdd,
        0x11, 0x22, 0x33, 0x44,
    };
    var scratch: [8]u8 = undefined;
    var reader: std.Io.Reader = .fixed(&packet);
    const reply = try xproto.GetPropertyReply.decode(&reader, &scratch);

    try std.testing.expectEqual(@as(u8, 32), reply.format);
    try std.testing.expectEqual(@as(u32, 57), reply.type_atom);
    try std.testing.expectEqual(@as(u32, 2), reply.value_len);
    try std.testing.expectEqualSlices(u8, &.{ 0xaa, 0xbb, 0xcc, 0xdd, 0x11, 0x22, 0x33, 0x44 }, reply.value);
}
