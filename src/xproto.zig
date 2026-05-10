const std = @import("std");
const gen = @import("gen/xproto.zig");
const Connection = @import("connection.zig").Connection;

pub const Atom = gen.Atom;
pub const Window = gen.Window;
pub const SetupRequest = gen.SetupRequest;
pub const Setup = gen.Setup;
pub const SetupFailed = gen.SetupFailed;
pub const SetupAuthenticate = gen.SetupAuthenticate;
pub const GetPropertyType = gen.GetPropertyType;
pub const InternAtomRequest = gen.InternAtomRequest;
pub const InternAtomReply = gen.InternAtomReply;
pub const GetPropertyRequest = gen.GetPropertyRequest;
pub const GetPropertyReply = gen.GetPropertyReply;
pub const GetInputFocusRequest = gen.GetInputFocusRequest;
pub const GetInputFocusReply = gen.GetInputFocusReply;

pub const PropertyView = struct {
    format: u8,
    type_atom: u32,
    value_len: u32,
    bytes: []const u8,

    pub fn u32s(self: PropertyView) ![]align(1) const u32 {
        if (self.format != 32) return error.UnexpectedFormat;
        if (self.value_len * 4 > self.bytes.len) return error.MalformedProperty;
        return std.mem.bytesAsSlice(u32, self.bytes[0 .. self.value_len * 4]);
    }
};

pub fn internAtom(conn: *Connection, name: []const u8) !u32 {
    _ = try conn.send(InternAtomRequest{
        .only_if_exists = false,
        .name = name,
    });

    const packet = try conn.readReplyPacket();
    var reader: std.Io.Reader = .fixed(packet);
    const reply = try InternAtomReply.decode(&reader);
    return reply.atom;
}

pub fn getProperty(
    conn: *Connection,
    window: u32,
    property: u32,
    property_type: u32,
    out: []u8,
) !PropertyView {
    _ = try conn.send(GetPropertyRequest{
        .delete_value = false,
        .window = window,
        .property = property,
        .type_atom = property_type,
        .long_offset = 0,
        .long_length = 4096,
    });

    const packet = try conn.readReplyPacket();
    var reader: std.Io.Reader = .fixed(packet);
    const reply = try GetPropertyReply.decode(&reader, out);
    if (reply.bytes_after != 0) return error.PropertyTruncated;

    return .{
        .format = reply.format,
        .type_atom = reply.type_atom,
        .value_len = reply.value_len,
        .bytes = reply.value,
    };
}
