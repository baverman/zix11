const std = @import("std");
const connection = @import("connection.zig");
const x = @import("gen/xproto.zig");

pub const Connection = connection.Connection;

pub const Type = struct {
    pub fn make(comptime T: type) type {
        return struct {
            property_type: x.Atom,

            const Self = @This();
            pub const Elem = T;
            pub const Buf = []Elem;
            pub const Slice = []const Elem;

            pub fn init(property_type: x.Atom) Self {
                return .{ .property_type = property_type };
            }

            pub fn as(_: Self, property_type: x.Atom) Self {
                return .{ .property_type = property_type };
            }
        };
    }

    pub const any: make(u8) = .init(x.Atom_.Any);
    pub const cardinal: make(u32) = .init(x.Atom.CARDINAL);
    pub const string: make(u8) = .init(x.Atom.STRING);
    pub const window: make(x.Window) = .init(x.Atom.WINDOW);
    pub const atom: make(x.Atom) = .init(x.Atom.ATOM);
};

pub fn get(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    property_type: anytype,
    buffer: @TypeOf(property_type).Buf,
) !@TypeOf(property_type).Slice {
    const T = @TypeOf(property_type).Elem;
    const expected_type = property_type.property_type;

    const reply = try conn.requestBuf(std.mem.sliceAsBytes(buffer), x.GetProperty, .{
        .delete = false,
        .window = window,
        .property = property,
        .type = expected_type,
        .long_offset = 0,
        .long_length = @intCast(buffer.len * @sizeOf(T) / 4),
    });

    if (reply.format == 0) {
        return buffer[0..0];
    }

    if (expected_type != x.Atom_.Any and reply.type != expected_type) return error.UnexpectedType;
    if (reply.format != propertyFormat(T)) return error.UnexpectedFormat;
    if (reply.bytes_after != 0) return error.PropertyTruncated;

    const byte_len = reply.value_len * (@as(usize, reply.format) / 8);
    if (byte_len > reply.value.len) return error.MalformedProperty;
    if (byte_len % @sizeOf(T) != 0) return error.MalformedProperty;

    return buffer[0 .. byte_len / @sizeOf(T)];
}

pub fn getScalar(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    property_type: anytype,
) !?@TypeOf(property_type).Elem {
    const T = @TypeOf(property_type).Elem;
    var buf: [1]T = undefined;
    const values = try get(conn, window, property, property_type, &buf);
    return if (values.len == 0) null else values[0];
}

pub fn set(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    property_type: anytype,
    data: @TypeOf(property_type).Slice,
) !void {
    const T = @TypeOf(property_type).Elem;
    try conn.request(x.ChangeProperty, .{
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
