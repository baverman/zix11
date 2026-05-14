const std = @import("std");

pub const errors = @import("errors.zig");
pub const extensions = @import("extensions.zig");
pub const xproto = @import("xproto.zig");
pub const render = @import("render.zig");
pub const Connection = @import("connection.zig").Connection;
pub const ProtocolError = @import("connection.zig").ProtocolError;

pub fn getProperty(
    conn: *Connection,
    window: xproto.Window,
    property: xproto.Atom,
    expected_type: xproto.Atom,
    comptime T: type,
    scratch: []align(@alignOf(T)) u8,
) ![]const T {
    const reply = try conn.requestBuf(scratch, xproto.GetProperty, .{
        .delete = false,
        .window = window,
        .property = property,
        .type = expected_type,
        .long_offset = 0,
        .long_length = @intCast(scratch.len / 4),
    });

    if (reply.type != expected_type) return error.UnexpectedType;
    if (reply.format != propertyFormat(T)) return error.UnexpectedFormat;
    if (reply.bytes_after != 0) return error.PropertyTruncated;

    const byte_len = reply.value_len * (@as(usize, reply.format) / 8);
    if (byte_len > reply.value.len) return error.MalformedProperty;
    if (byte_len % @sizeOf(T) != 0) return error.MalformedProperty;

    const aligned_bytes: []align(@alignOf(T)) const u8 = @alignCast(reply.value[0..byte_len]);
    const ptr: [*]align(@alignOf(T)) const T = @ptrCast(aligned_bytes.ptr);
    return ptr[0 .. byte_len / @sizeOf(T)];
}

fn propertyFormat(comptime T: type) u8 {
    if (T == u8) return 8;
    if (T == u16) return 16;
    if (T == u32) return 32;

    const info = @typeInfo(T);
    if (info == .@"enum" and @typeInfo(info.@"enum".tag_type) == .int and @sizeOf(T) == 4) {
        return 32;
    }

    @compileError("unsupported property element type");
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
    try std.testing.expectEqual(@as(u16, 7), std.mem.readInt(u16, body[1..3], .little));
    try std.testing.expectEqualSlices(u8, "WM_NAME", body[3..10]);
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
