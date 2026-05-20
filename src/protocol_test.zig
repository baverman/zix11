const std = @import("std");
const events = @import("events.zig");
const ext = @import("ext.zig");
const protocol = @import("protocol.zig");
const x = @import("gen/xproto.zig");

test "Protocol.send frames core requests with opcode and header byte 1" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    var buf: [64]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = x.InternAtom{
        .only_if_exists = true,
        .name = "WM_NAME",
    };

    const sequence = try proto.send(&writer, req, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(u16, 1), sequence);
    try std.testing.expectEqual(@as(u8, x.InternAtom.opcode), packet[0]);
    try std.testing.expectEqual(req.headerByte1(), packet[1]);
    try std.testing.expectEqual(@as(u16, 4), std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(@as(usize, 16), packet.len);
    try std.testing.expectEqualSlices(u8, "WM_NAME", packet[8..15]);
    try std.testing.expectEqual(@as(u8, 0), packet[15]);
}

test "Protocol.send frames MIT-SHM requests with registered major opcode and request opcode" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.MIT_SHM, .{
        .major_opcode = 137,
        .first_event = 64,
        .first_error = 128,
    });

    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);

    const sequence = try proto.send(&writer, ext.shm.QueryVersion{}, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(u16, 1), sequence);
    try std.testing.expectEqual(@as(u8, 137), packet[0]);
    try std.testing.expectEqual(@as(u8, ext.shm.QueryVersion.opcode), packet[1]);
    try std.testing.expectEqual(@as(u16, 1), std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(@as(usize, 4), packet.len);
}

test "Protocol.send frames RENDER requests with registered major opcode and padded length" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.RENDER, .{
        .major_opcode = 138,
        .first_event = 96,
        .first_error = 160,
    });

    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = ext.render.QueryVersion{
        .client_major_version = 0,
        .client_minor_version = 11,
    };

    const sequence = try proto.send(&writer, req, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(u16, 1), sequence);
    try std.testing.expectEqual(@as(u8, 138), packet[0]);
    try std.testing.expectEqual(@as(u8, ext.render.QueryVersion.opcode), packet[1]);
    try std.testing.expectEqual(@as(u16, 3), std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(@as(u32, 0), std.mem.readInt(u32, packet[4..8], .native));
    try std.testing.expectEqual(@as(u32, 11), std.mem.readInt(u32, packet[8..12], .native));
    try std.testing.expectEqual(@as(usize, 12), packet.len);
}

test "Protocol.send frames XFIXES requests with registered major opcode and request opcode" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.XFIXES, .{
        .major_opcode = 139,
        .first_event = 110,
        .first_error = 170,
    });

    var buf: [32]u8 = undefined;
    var writer: std.Io.Writer = .fixed(&buf);
    const req = ext.xfixes.QueryVersion{
        .client_major_version = 6,
        .client_minor_version = 0,
    };

    const sequence = try proto.send(&writer, req, false);
    const packet = buf[0..writer.end];

    try std.testing.expectEqual(@as(u16, 1), sequence);
    try std.testing.expectEqual(@as(u8, 139), packet[0]);
    try std.testing.expectEqual(@as(u8, ext.xfixes.QueryVersion.opcode), packet[1]);
    try std.testing.expectEqual(@as(u16, 3), std.mem.readInt(u16, packet[2..4], .native));
    try std.testing.expectEqual(@as(u32, 6), std.mem.readInt(u32, packet[4..8], .native));
    try std.testing.expectEqual(@as(u32, 0), std.mem.readInt(u32, packet[8..12], .native));
    try std.testing.expectEqual(@as(usize, 12), packet.len);
}

test "Protocol.readEvent decodes registered XFIXES events into global Event" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.XFIXES, .{
        .major_opcode = 139,
        .first_event = 110,
        .first_error = 170,
        .event_spec = events.eventSpec(.XFIXES),
    });

    var packet = std.mem.zeroes([32]u8);
    packet[0] = 110;
    packet[1] = 0;
    std.mem.writeInt(u16, packet[2..4], 21, .native);

    var reader: std.Io.Reader = .fixed(&packet);
    const event = try proto.readEvent(&reader);

    switch (event) {
        .XFixesSelectionNotify => |ev| try std.testing.expectEqual(ext.xfixes.SelectionEvent.SetSelectionOwner, ev.subtype),
        else => return error.TestUnexpectedResult,
    }
}

test "Protocol.pendingEvent decodes queued core events into global Event" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    var packet = std.mem.zeroes([32]u8);
    packet[0] = 12;
    std.mem.writeInt(u16, packet[2..4], 9, .native);
    std.mem.writeInt(u16, packet[16..18], 4, .native);
    try proto.pending_events.pushBack(std.testing.allocator, packet);

    const event = (try proto.pendingEvent()) orelse return error.TestUnexpectedResult;
    switch (event) {
        .Expose => |ev| try std.testing.expectEqual(@as(u16, 4), ev.count),
        else => return error.TestUnexpectedResult,
    }
}
