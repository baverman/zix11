const std = @import("std");
const connection = @import("connection.zig");
const x = @import("gen/xproto.zig");

pub const Connection = connection.Connection;

pub fn get(conn: *Connection, window: x.Window, property: x.Atom, arg: anytype) !GetResult(
    @TypeOf(arg),
    if (@TypeOf(arg) == type) arg else null,
) {
    const property_type = defaultPropertyAtom(
        @TypeOf(arg),
        if (@TypeOf(arg) == type) arg else null,
    );
    return switch (@typeInfo(@TypeOf(arg))) {
        .type => getScalarImpl(conn, window, property, property_type, arg),
        .pointer => getSliceImpl(conn, window, property, property_type, std.meta.Elem(@TypeOf(arg)), arg),
        else => @compileError("expected type or slice buffer"),
    };
}

pub fn getAs(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    property_type: x.Atom,
    arg: anytype,
) !GetResult(@TypeOf(arg), if (@TypeOf(arg) == type) arg else null) {
    return switch (@typeInfo(@TypeOf(arg))) {
        .type => getScalarImpl(conn, window, property, property_type, arg),
        .pointer => getSliceImpl(conn, window, property, property_type, std.meta.Elem(@TypeOf(arg)), arg),
        else => @compileError("expected type or slice buffer"),
    };
}

pub fn setAs(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    property_type: x.Atom,
    data: anytype,
) !void {
    const T = @TypeOf(data);
    return switch (@typeInfo(T)) {
        .pointer => setSliceImpl(conn, window, property, property_type, std.meta.Elem(T), data[0..]),
        else => setSliceImpl(conn, window, property, property_type, T, &.{data}),
    };
}

pub fn set(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    data: anytype,
) !void {
    const T = @TypeOf(data);

    return switch (@typeInfo(T)) {
        .pointer => setSliceImpl(conn, window, property, defaultPropertyAtomForElem(std.meta.Elem(T)), std.meta.Elem(T), data[0..]),
        else => setSliceImpl(conn, window, property, defaultPropertyAtomForElem(T), T, &.{data}),
    };
}

fn setSliceImpl(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    property_type: x.Atom,
    comptime T: type,
    data: []const T,
) !void {
    try conn.request(x.ChangeProperty, .{
        .mode = .Replace,
        .window = window,
        .property = property,
        .type = property_type,
        .format = propertyFormat(T),
        .data_len = @intCast(data.len),
        .data = std.mem.sliceAsBytes(data),
    });
}

fn GetResult(comptime Arg: type, comptime Elem: ?type) type {
    return switch (@typeInfo(Arg)) {
        .type => ?Elem.?,
        .pointer => []const std.meta.Elem(Arg),
        else => @compileError("expected type or slice buffer"),
    };
}

fn getScalarImpl(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    property_type: x.Atom,
    comptime T: type,
) !?T {
    var buf: [1]T = undefined;
    const values = try getSliceImpl(conn, window, property, property_type, T, &buf);
    return if (values.len == 0) null else values[0];
}

fn getSliceImpl(
    conn: *Connection,
    window: x.Window,
    property: x.Atom,
    property_type: x.Atom,
    comptime T: type,
    buffer: []T,
) ![]const T {
    const reply = try conn.requestBuf(std.mem.sliceAsBytes(buffer), x.GetProperty, .{
        .delete = false,
        .window = window,
        .property = property,
        .type = property_type,
        .long_offset = 0,
        .long_length = @intCast(buffer.len * @sizeOf(T) / 4),
    });

    if (reply.format == 0) return buffer[0..0];
    if (property_type != x.Atom_.Any and reply.type != property_type) return error.UnexpectedType;
    if (reply.format != propertyFormat(T)) return error.UnexpectedFormat;
    if (reply.bytes_after != 0) return error.PropertyTruncated;

    const byte_len = reply.value_len * (@as(usize, reply.format) / 8);
    if (byte_len > reply.value.len) return error.MalformedProperty;
    if (byte_len % @sizeOf(T) != 0) return error.MalformedProperty;

    return buffer[0 .. byte_len / @sizeOf(T)];
}

fn defaultPropertyAtom(comptime Arg: type, comptime Elem: ?type) x.Atom {
    return switch (@typeInfo(Arg)) {
        .type => defaultPropertyAtomForElem(Elem.?),
        .pointer => defaultPropertyAtomForElem(std.meta.Elem(Arg)),
        else => @compileError("expected type or slice buffer"),
    };
}

fn defaultPropertyAtomForElem(comptime T: type) x.Atom {
    if (T == u8) return x.Atom_.Any;
    if (T == u32) return x.Atom.CARDINAL;
    if (T == x.Window) return x.Atom.WINDOW;
    if (T == x.Atom) return x.Atom.ATOM;
    @compileError("no default property atom mapping for type");
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
