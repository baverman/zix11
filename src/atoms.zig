const Connection = @import("connection.zig").Connection;
const x = @import("gen/xproto.zig");

pub fn get(conn: *Connection, name: []const u8) !x.Atom {
    const reply = try conn.request(x.InternAtom, .{
        .only_if_exists = true,
        .name = name,
    });
    return reply.atom;
}

pub fn getOrCreate(conn: *Connection, name: []const u8) !x.Atom {
    const reply = try conn.request(x.InternAtom, .{
        .only_if_exists = false,
        .name = name,
    });
    return reply.atom;
}

pub fn AtomStruct(comptime E: type) type {
    return @Struct(.auto, null, @import("std").meta.fieldNames(E), &@splat(x.Atom), &@splat(.{}));
}

pub fn getAll(comptime T: type, conn: *Connection) !T {
    var result: T = undefined;
    inline for (@typeInfo(T).@"struct".fields) |field| {
        @field(result, field.name) = try get(conn, field.name);
    }
    return result;
}
