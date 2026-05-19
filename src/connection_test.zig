const std = @import("std");
const connection = @import("connection.zig");
const protocol = @import("protocol.zig");

test "Connection.taggedError decodes core protocol errors" {
    var proto = protocol.Protocol.init(std.testing.allocator);
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
    var proto = protocol.Protocol.init(std.testing.allocator);
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
    var proto = protocol.Protocol.init(std.testing.allocator);
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
    var proto = protocol.Protocol.init(std.testing.allocator);
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
