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
    try proto.pending_events.pushBack(std.testing.allocator, .{
        .fixed = .{
            .data = blk: {
                var raw = std.mem.zeroes([64]u8);
                @memcpy(raw[0..packet.len], packet[0..]);
                break :blk raw;
            },
            .len = packet.len,
        },
    });

    const event = (try proto.pendingEvent()) orelse return error.TestUnexpectedResult;
    switch (event) {
        .Expose => |ev| try std.testing.expectEqual(@as(u16, 4), ev.count),
        else => return error.TestUnexpectedResult,
    }
}

test "Protocol.pendingEvent preserves queued GE packet length" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();

    var packet = std.mem.zeroes([38]u8);
    packet[0] = 35;
    packet[1] = 42;
    std.mem.writeInt(u16, packet[2..4], 17, .native);
    std.mem.writeInt(u32, packet[4..8], 0, .native);
    std.mem.writeInt(u16, packet[8..10], 99, .native);

    try proto.queueEventPacket(&packet);

    const event = (try proto.pendingEvent()) orelse return error.TestUnexpectedResult;
    switch (event) {
        .GeGeneric => |ev| {
            try std.testing.expectEqual(@as(u8, 42), ev.extension);
            try std.testing.expectEqual(@as(u32, 0), ev.length);
            try std.testing.expectEqual(@as(u16, 99), ev.event_type);
        },
        else => return error.TestUnexpectedResult,
    }
}

test "Protocol.readEvent decodes XInputMotion XGE packets" {
    var proto = protocol.Protocol.init(std.testing.allocator);
    defer proto.deinit();
    proto.extensions.put(.XINPUT, .{
        .major_opcode = 131,
        .first_event = 64,
        .first_error = 128,
        .event_spec = events.eventSpec(.XINPUT),
    });

    var packet = std.mem.zeroes([100]u8);
    packet[0] = 35;
    packet[1] = 131;
    std.mem.writeInt(u16, packet[2..4], 17, .native);
    std.mem.writeInt(u32, packet[4..8], 17, .native);
    std.mem.writeInt(u16, packet[8..10], 6, .native);
    std.mem.writeInt(u16, packet[10..12], 12, .native);
    std.mem.writeInt(u32, packet[12..16], 0x01020304, .native);
    std.mem.writeInt(u32, packet[16..20], 9, .native);
    std.mem.writeInt(u32, packet[20..24], 0x11111111, .native);
    std.mem.writeInt(u32, packet[24..28], 0x22222222, .native);
    std.mem.writeInt(u32, packet[28..32], 0x33333333, .native);
    std.mem.writeInt(i32, packet[32..36], 10 << 16, .native);
    std.mem.writeInt(i32, packet[36..40], 20 << 16, .native);
    std.mem.writeInt(i32, packet[40..44], 30 << 16, .native);
    std.mem.writeInt(i32, packet[44..48], 40 << 16, .native);
    std.mem.writeInt(u16, packet[48..50], 1, .native);
    std.mem.writeInt(u16, packet[50..52], 1, .native);
    std.mem.writeInt(u16, packet[52..54], 13, .native);
    std.mem.writeInt(u32, packet[56..60], 0x00010000, .native);
    std.mem.writeInt(u32, packet[60..64], 1, .native);
    std.mem.writeInt(u32, packet[64..68], 2, .native);
    std.mem.writeInt(u32, packet[68..72], 3, .native);
    std.mem.writeInt(u32, packet[72..76], 4, .native);
    packet[76] = 5;
    packet[77] = 6;
    packet[78] = 7;
    packet[79] = 8;
    std.mem.writeInt(u32, packet[80..84], 0x10, .native);
    std.mem.writeInt(u32, packet[84..88], 0x1, .native);
    std.mem.writeInt(i32, packet[88..92], 50, .native);
    std.mem.writeInt(u32, packet[92..96], 0x80000000, .native);

    var reader: std.Io.Reader = .fixed(&packet);
    const event = try proto.readEvent(&reader);

    switch (event) {
        .XInputMotion => |ev| {
            try std.testing.expectEqual(@as(u8, 131), ev.extension);
            try std.testing.expectEqual(@as(u32, 17), ev.length);
            try std.testing.expectEqual(@as(u16, 6), ev.event_type);
            try std.testing.expectEqual(@as(u16, 12), ev.deviceid);
            try std.testing.expectEqual(@as(u32, 0x01020304), ev.time);
            try std.testing.expectEqual(@as(u32, 9), ev.detail);
            try std.testing.expectEqual(@as(x.Window, @enumFromInt(0x11111111)), ev.root);
            try std.testing.expectEqual(@as(x.Window, @enumFromInt(0x22222222)), ev.event);
            try std.testing.expectEqual(@as(x.Window, @enumFromInt(0x33333333)), ev.child);
            try std.testing.expectEqual(@as(i32, 10 << 16), ev.root_x);
            try std.testing.expectEqual(@as(i32, 20 << 16), ev.root_y);
            try std.testing.expectEqual(@as(i32, 30 << 16), ev.event_x);
            try std.testing.expectEqual(@as(i32, 40 << 16), ev.event_y);
            try std.testing.expectEqual(@as(u16, 1), ev.buttons_len);
            try std.testing.expectEqual(@as(u16, 1), ev.valuators_len);
            try std.testing.expectEqual(@as(u16, 13), ev.sourceid);
            try std.testing.expectEqual(@as(u32, 0x00010000), ev.flags);
            try std.testing.expectEqual(@as(u32, 4), ev.mods.effective);
            try std.testing.expectEqual(@as(u8, 8), ev.group.effective);

            var body = try ev.getBody(std.testing.allocator);
            defer body.deinit(std.testing.allocator);
            try std.testing.expectEqual(@as(usize, 1), body.button_mask.len);
            try std.testing.expectEqual(@as(usize, 1), body.valuator_mask.len);
            try std.testing.expectEqual(@as(usize, 1), body.axisvalues.len);
            try std.testing.expectEqual(@as(u32, 0x10), body.button_mask[0]);
            try std.testing.expectEqual(@as(u32, 0x1), body.valuator_mask[0]);
            try std.testing.expectEqual(@as(i32, 50), body.axisvalues[0].integral);
            try std.testing.expectEqual(@as(u32, 0x80000000), body.axisvalues[0].frac);
        },
        else => return error.TestUnexpectedResult,
    }
}
