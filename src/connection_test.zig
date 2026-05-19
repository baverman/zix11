const std = @import("std");
const connection = @import("connection.zig");
const render = @import("render.zig");
const shm = @import("shm.zig");
const xproto = @import("xproto.zig");

test "Protocol.send frames core requests with opcode and header byte 1" {
    var proto = connection.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    var buf: [64]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = xproto.InternAtom{
        .only_if_exists = true,
        .name = "WM_NAME",
    };

    const sequence = try proto.send(&writer, req, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(u16, 1), sequence);
    try std.testing.expectEqual(@as(u8, xproto.InternAtom.opcode), packet[0]);
    try std.testing.expectEqual(req.headerByte1(), packet[1]);
    try std.testing.expectEqual(@as(u16, 4), std.mem.readInt(u16, packet[2..4], .little));
    try std.testing.expectEqual(@as(usize, 16), packet.len);
    try std.testing.expectEqualSlices(u8, "WM_NAME", packet[8..15]);
    try std.testing.expectEqual(@as(u8, 0), packet[15]);
}

test "Protocol.send frames MIT-SHM requests with registered major opcode and request opcode" {
    var proto = connection.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.MIT_SHM, .{
        .major_opcode = 137,
        .first_event = 64,
        .first_error = 128,
    });

    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);

    const sequence = try proto.send(&writer, shm.QueryVersion{}, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(u16, 1), sequence);
    try std.testing.expectEqual(@as(u8, 137), packet[0]);
    try std.testing.expectEqual(@as(u8, shm.QueryVersion.opcode), packet[1]);
    try std.testing.expectEqual(@as(u16, 1), std.mem.readInt(u16, packet[2..4], .little));
    try std.testing.expectEqual(@as(usize, 4), packet.len);
}

test "Protocol.send frames RENDER requests with registered major opcode and padded length" {
    var proto = connection.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.RENDER, .{
        .major_opcode = 138,
        .first_event = 96,
        .first_error = 160,
    });

    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = render.QueryVersion{
        .client_major_version = 0,
        .client_minor_version = 11,
    };

    const sequence = try proto.send(&writer, req, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(u16, 1), sequence);
    try std.testing.expectEqual(@as(u8, 138), packet[0]);
    try std.testing.expectEqual(@as(u8, render.QueryVersion.opcode), packet[1]);
    try std.testing.expectEqual(@as(u16, 3), std.mem.readInt(u16, packet[2..4], .little));
    try std.testing.expectEqual(@as(u32, 0), std.mem.readInt(u32, packet[4..8], .little));
    try std.testing.expectEqual(@as(u32, 11), std.mem.readInt(u32, packet[8..12], .little));
    try std.testing.expectEqual(@as(usize, 12), packet.len);
}

test "Connection.taggedError decodes core protocol errors" {
    var proto = connection.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    var dummy_transport: connection.StreamTransport = undefined;
    const conn = connection.Connection{
        .allocator = std.testing.allocator,
        .proto = &proto,
        .transport = &dummy_transport,
        .root_window = @enumFromInt(0),
    };

    proto.last_protocol_error = .{
        .code = 3,
        .sequence = 17,
        .bad_value = 0xdeadbeef,
        .minor_opcode = 0,
        .major_opcode = 0,
        .tail = [_]u8{0} ** 20,
    };

    switch (conn.lastError(error.X11ProtocolError)) {
        .Window => |e| {
            try std.testing.expectEqual(@as(u8, 3), e.code);
            try std.testing.expectEqual(@as(u32, 0xdeadbeef), e.bad_value);
        },
        else => return error.TestUnexpectedResult,
    }
}

test "Connection.taggedError decodes extension protocol errors" {
    var proto = connection.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.RENDER, .{
        .major_opcode = 138,
        .first_event = 96,
        .first_error = 160,
    });

    var dummy_transport: connection.StreamTransport = undefined;
    const conn = connection.Connection{
        .allocator = std.testing.allocator,
        .proto = &proto,
        .transport = &dummy_transport,
        .root_window = @enumFromInt(0),
    };

    proto.last_protocol_error = .{
        .code = 160,
        .sequence = 18,
        .bad_value = 0x1234,
        .minor_opcode = 4,
        .major_opcode = 138,
        .tail = [_]u8{0} ** 20,
    };

    switch (conn.lastError(error.X11ProtocolError)) {
        .RenderPictFormat => |e| {
            try std.testing.expectEqual(@as(u8, 160), e.code);
            try std.testing.expectEqual(@as(u16, 18), e.sequence);
        },
        else => return error.TestUnexpectedResult,
    }
}

test "Connection.taggedError keeps non-X11 errors explicit" {
    var proto = connection.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    var dummy_transport: connection.StreamTransport = undefined;
    const conn = connection.Connection{
        .allocator = std.testing.allocator,
        .proto = &proto,
        .transport = &dummy_transport,
        .root_window = @enumFromInt(0),
    };

    switch (conn.lastError(error.UnexpectedReply)) {
        .NonX11 => |err| try std.testing.expectEqual(error.UnexpectedReply, err),
        else => return error.TestUnexpectedResult,
    }
}

test "Connection.taggedError preserves unknown X11 errors" {
    var proto = connection.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.MIT_SHM, .{
        .major_opcode = 137,
        .first_event = 64,
        .first_error = 128,
    });

    var dummy_transport: connection.StreamTransport = undefined;
    const conn = connection.Connection{
        .allocator = std.testing.allocator,
        .proto = &proto,
        .transport = &dummy_transport,
        .root_window = @enumFromInt(0),
    };

    proto.last_protocol_error = .{
        .code = 200,
        .sequence = 19,
        .bad_value = 0xbeef,
        .minor_opcode = 9,
        .major_opcode = 137,
        .tail = [_]u8{0} ** 20,
    };

    switch (conn.lastError(error.X11ProtocolError)) {
        .Unknown => |e| try std.testing.expectEqual(@as(u8, 200), e.code),
        else => return error.TestUnexpectedResult,
    }
}
