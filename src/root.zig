const std = @import("std");

pub const errors = @import("errors.zig");
pub const extensions = @import("extensions.zig");
pub const xproto = @import("xproto.zig");
pub const render = @import("render.zig");
pub const shm = @import("shm.zig");
pub const Connection = @import("connection.zig").Connection;
pub const ProtocolError = @import("connection.zig").ProtocolError;
pub const ewmh = @import("ewmh.zig");

pub const PropertyType = struct {
    pub fn make(comptime Type: type) type {
        return struct {
            property_type: xproto.Atom,

            const Self = @This();
            pub const T = Type;
            pub const Buf = []T;
            pub const Slice = []const T;

            pub fn init(property_type: xproto.Atom) Self {
                return .{ .property_type = property_type };
            }

            pub fn as(_: Self, property_type: xproto.Atom) Self {
                return .{ .property_type = property_type };
            }
        };
    }

    pub const any: make(u8) = .init(xproto.Atom_.Any);
    pub const cardinal: make(u32) = .init(xproto.Atom.CARDINAL);
    pub const string: make(u8) = .init(xproto.Atom.STRING);
    pub const window: make(xproto.Window) = .init(xproto.Atom.WINDOW);
    pub const atom: make(xproto.Atom) = .init(xproto.Atom.ATOM);
};

pub fn getProperty(
    conn: *Connection,
    window: xproto.Window,
    property: xproto.Atom,
    property_type: anytype,
    buffer: @TypeOf(property_type).Buf,
) !@TypeOf(property_type).Slice {
    const T = @TypeOf(property_type).T;
    const expected_type = property_type.property_type;

    const reply = try conn.requestBuf(std.mem.sliceAsBytes(buffer), xproto.GetProperty, .{
        .delete = false,
        .window = window,
        .property = property,
        .type = expected_type,
        .long_offset = 0,
        .long_length = @intCast(buffer.len * @sizeOf(T) / 4),
    });

    if (expected_type != xproto.Atom_.Any and reply.type != expected_type) return error.UnexpectedType;
    if (reply.format != propertyFormat(T)) return error.UnexpectedFormat;
    if (reply.bytes_after != 0) return error.PropertyTruncated;

    const byte_len = reply.value_len * (@as(usize, reply.format) / 8);
    if (byte_len > reply.value.len) return error.MalformedProperty;
    if (byte_len % @sizeOf(T) != 0) return error.MalformedProperty;

    return buffer[0 .. byte_len / @sizeOf(T)];
}

pub fn getScalarProperty(
    conn: *Connection,
    window: xproto.Window,
    property: xproto.Atom,
    property_type: anytype,
) !?@TypeOf(property_type).T {
    const T = @TypeOf(property_type).T;
    var buf: [1]T = undefined;
    const values = try getProperty(conn, window, property, property_type, &buf);
    return if (values.len == 0) null else values[0];
}

pub fn setProperty(
    conn: *Connection,
    window: xproto.Window,
    property: xproto.Atom,
    property_type: anytype,
    data: @TypeOf(property_type).Slice,
) !void {
    const T = @TypeOf(property_type).T;
    try conn.request(xproto.ChangeProperty, .{
        .mode = .Replace,
        .window = window,
        .property = property,
        .type = property_type.property_type,
        .format = propertyFormat(T),
        .data_len = @intCast(data.len),
        .data = std.mem.sliceAsBytes(data),
    });
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

pub fn clientMessageData(comptime T: type, data: []const T) xproto.ClientMessageData {
    var result: xproto.ClientMessageData = .{ .data8 = std.mem.zeroes([20]u8)};
    const bdata = std.mem.sliceAsBytes(data);
    const len = @min(result.data8.len, bdata.len);
    @memcpy(result.data8[0..len], bdata[0..len]);
    return result;
}

pub fn internAtom(conn: *Connection, name: []const u8, only_if_exists: bool) !xproto.Atom {
    const reply = try conn.request(xproto.InternAtom, .{
        .only_if_exists = only_if_exists,
        .name = name,
    });
    return reply.atom;
}

pub fn AtomEnum(comptime E: type) type {
    const S = @Struct(.auto, null, std.meta.fieldNames(E), &@splat(xproto.Atom), &@splat(.{}));
    return struct {
        pub const Struct = S;
        pub fn init(conn: *Connection) !S {
            var result: S = undefined;
            inline for (@typeInfo(E).@"enum".fields) |field| {
                @field(result, field.name) = try internAtom(conn, field.name, false);
            }
            return result;
        }
    };
}

test {
    _ = ewmh;
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
        .data = clientMessageData(u32, &.{ 10, 20 }),
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
