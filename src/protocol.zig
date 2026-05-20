const std = @import("std");
const builtin = @import("builtin");
const errors = @import("errors.zig");
const ext = @import("ext.zig");
const events = @import("events.zig");
const wire = @import("_wire.zig");
const x = @import("gen/xproto.zig");

pub const ProtocolError = errors.ProtocolError;

pub const ReplyMode = enum {
    fixed,
    alloc,
    buffer,
};

pub const WriterReader = struct {
    writer: *std.Io.Writer,
    reader: *std.Io.Reader,
};

pub const Protocol = struct {
    allocator: std.mem.Allocator,
    root_window: x.Window,
    resource_id_base: u32,
    resource_id_mask: u32,
    resource_id_inc: u32,
    next_resource_id: u32,
    pending_events: std.Deque([32]u8),
    last_protocol_error: ?ProtocolError,
    sequence: u16 = 1,
    extensions: std.enums.EnumMap(ext.Extension, ext.ExtensionInfo),

    pub fn init(allocator: std.mem.Allocator) Protocol {
        return .{
            .allocator = allocator,
            .root_window = @enumFromInt(0),
            .resource_id_base = 0,
            .resource_id_mask = 0,
            .resource_id_inc = 0,
            .next_resource_id = 0,
            .pending_events = .empty,
            .last_protocol_error = null,
            .extensions = .{},
        };
    }

    pub fn deinit(self: *Protocol) void {
        self.pending_events.deinit(self.allocator);
    }

    pub fn readReplyPacket(self: *Protocol, reader: *std.Io.Reader) ![]const u8 {
        _ = self;
        const header = try reader.peek(32);
        const packet_kind = header[0];
        const extra_len = if (packet_kind == 1)
            @as(usize, std.mem.readInt(u32, header[4..8], .native)) * 4
        else
            0;
        const packet_len = 32 + extra_len;
        return try reader.take(packet_len);
    }

    pub fn readEvent(self: *Protocol, reader: *std.Io.Reader) !events.Event {
        while (true) {
            const packet = try self.readReplyPacket(reader);
            if (packet[0] == 0) {
                self.last_protocol_error = parseProtocolError(packet);
                continue;
            }
            return try self.decodeEventPacket(packet);
        }
    }

    pub fn pendingEvent(self: *Protocol) !?events.Event {
        if (self.pending_events.popFront()) |raw| {
            return try self.decodeEventPacket(&raw);
        }
        return null;
    }

    pub fn hasPendingEvents(self: *Protocol) bool {
        return self.pending_events.len != 0;
    }

    pub fn send(self: *Protocol, writer: *std.Io.Writer, request_value: anytype, flush: bool) !u16 {
        const Request = @TypeOf(request_value);
        const sequence = self.sequence;
        self.sequence +%= 1;
        const body_len = request_value.byteLen();
        const len = 4 + body_len;
        const pad = wire.pad4(len);
        const opcode = if (Request.extension) |extension| blk: {
            const info = self.extensions.get(extension) orelse return error.ExtensionNotRegistered;
            break :blk info.major_opcode;
        } else Request.opcode;

        try writer.writeByte(opcode);
        if (Request.extension == null) {
            try writer.writeByte(request_value.headerByte1());
        } else {
            try writer.writeByte(Request.opcode);
        }
        try writer.writeInt(u16, @intCast((len + pad) / 4), .native);
        try request_value.encode(writer);
        try writer.splatByteAll(0, pad);
        if (flush) try writer.flush();
        return sequence;
    }

    pub fn requestWithStorage(
        self: *Protocol,
        wr: WriterReader,
        comptime Request: type,
        req: Request,
        comptime reply_mode: ReplyMode,
        storage: anytype,
    ) !Request.Reply {
        const Reply = Request.Reply;
        if (Reply == void) {
            const request_sequence = try self.send(wr.writer, req, true);
            try self.sync(wr, request_sequence);
            return;
        }
        _ = try self.send(wr.writer, req, true);
        while (true) {
            const packet = try self.readReplyPacket(wr.reader);
            switch (packet[0]) {
                0 => {
                    self.last_protocol_error = parseProtocolError(packet);
                    return error.X11ProtocolError;
                },
                1 => {
                    var packet_reader: std.Io.Reader = .fixed(packet);
                    return switch (reply_mode) {
                        .fixed => try Reply.decode(&packet_reader),
                        .alloc => try Reply.decode(storage, &packet_reader),
                        .buffer => try Reply.decode(storage, &packet_reader),
                    };
                },
                else => try self.queueEventPacket(packet),
            }
        }
    }

    pub fn registerExtension(self: *Protocol, wr: WriterReader, extension: ext.Extension) !void {
        const reply = try self.requestWithStorage(wr, x.QueryExtension, .{
            .name = ext.xname(extension),
        }, .fixed, .{});
        if (!reply.present) return error.ExtensionUnavailable;
        self.extensions.put(extension, .{
            .major_opcode = reply.major_opcode,
            .first_event = reply.first_event,
            .first_error = reply.first_error,
            .event_spec = events.eventSpec(extension),
        });
    }

    fn decodeEventPacket(self: *Protocol, packet: []const u8) !events.Event {
        var raw: [32]u8 = undefined;
        std.debug.assert(packet.len == 32);
        @memcpy(raw[0..], packet[0..32]);

        const wire_code = raw[0] & 0x7f;
        if (wire_code >= 2 and wire_code <= 35) {
            var reader: std.Io.Reader = .fixed(&raw);
            return events.wrapEvent(events.Event, try x.decodeEvent(&reader));
        }

        var it = self.extensions.iterator();
        while (it.next()) |entry| {
            const info = entry.value;
            const spec = info.event_spec orelse continue;
            if (wire_code >= info.first_event and wire_code <= info.first_event + spec.max_event_num) {
                raw[0] = (raw[0] & 0x80) | (wire_code - info.first_event);
                return try spec.decode(raw);
            }
        }

        return .{ .Unknown = .{
            .code = wire_code,
            .sequence = std.mem.readInt(u16, raw[2..4], .native),
            .raw = raw,
        } };
    }

    pub fn sync(self: *Protocol, wr: WriterReader, request_sequence: u16) !void {
        const sync_sequence = try self.send(wr.writer, x.GetInputFocus{}, true);
        var request_failed = false;
        while (true) {
            const packet = try self.readReplyPacket(wr.reader);
            switch (packet[0]) {
                0 => {
                    const protocol_error = parseProtocolError(packet);
                    self.last_protocol_error = protocol_error;
                    if (protocol_error.sequence == request_sequence) {
                        request_failed = true;
                        continue;
                    }
                    return error.UnexpectedProtocolError;
                },
                1 => {
                    const reply_sequence = std.mem.readInt(u16, packet[2..4], .native);
                    var packet_reader: std.Io.Reader = .fixed(packet);
                    const reply = try x.GetInputFocusReply.decode(&packet_reader);
                    _ = reply;
                    if (reply_sequence != sync_sequence) {
                        return error.UnexpectedReply;
                    }
                    if (request_failed) {
                        return error.X11ProtocolError;
                    }
                    return;
                },
                else => try self.queueEventPacket(packet),
            }
        }
    }

    pub fn allocId(self: *Protocol, comptime T: type) !T {
        if (self.resource_id_mask == 0 or self.resource_id_inc == 0) return error.ResourceIdsExhausted;
        if ((self.next_resource_id & ~self.resource_id_mask) != 0) return error.ResourceIdsExhausted;
        const id = self.resource_id_base | self.next_resource_id;
        self.next_resource_id +%= self.resource_id_inc;
        return @as(T, @enumFromInt(id));
    }

    pub fn sendSetup(self: *Protocol, writer: *std.Io.Writer, cookie: []const u8) !void {
        _ = self;
        try (x.SetupRequest{
            .byte_order = switch (builtin.cpu.arch.endian()) {
                .little => 'l',
                .big => 'B',
            },
            .protocol_major_version = 11,
            .protocol_minor_version = 0,
            .authorization_protocol_name = "MIT-MAGIC-COOKIE-1",
            .authorization_protocol_data = cookie,
        }).encode(writer);
        try writer.flush();
    }

    pub fn readSetupReply(self: *Protocol, reader: *std.Io.Reader) !void {
        const packet = try self.readSetupPacket(reader);
        const status = packet[0];
        var packet_reader: std.Io.Reader = .fixed(packet);
        switch (status) {
            1 => {
                var setup = try x.Setup.decode(self.allocator, &packet_reader);
                defer setup.deinit(self.allocator);
                if (setup.roots.len == 0) return error.MalformedPacket;
                const screen = setup.roots[0];
                self.root_window = screen.root;
                self.resource_id_base = setup.resource_id_base;
                self.resource_id_mask = setup.resource_id_mask;
                self.resource_id_inc = lowestSetBit(setup.resource_id_mask);
                self.next_resource_id = 0;
            },
            0 => {
                var failed = try x.SetupFailed.decode(self.allocator, &packet_reader);
                defer failed.deinit(self.allocator);
                return error.X11SetupFailed;
            },
            2 => {
                var auth = try x.SetupAuthenticate.decode(self.allocator, &packet_reader);
                defer auth.deinit(self.allocator);
                return error.X11SetupAuthenticate;
            },
            else => return error.X11SetupUnknown,
        }
    }

    pub fn readSetupPacket(self: *const Protocol, reader: *std.Io.Reader) ![]const u8 {
        _ = self;
        const prefix = try reader.peek(8);
        const extra_len = @as(usize, std.mem.readInt(u16, prefix[6..8], .native)) * 4;
        const packet_len = 8 + extra_len;
        return try reader.take(packet_len);
    }

    pub fn queueEventPacket(self: *Protocol, packet: []const u8) !void {
        std.debug.assert(packet.len == 32);
        var raw: [32]u8 = undefined;
        @memcpy(raw[0..], packet[0..32]);
        try self.pending_events.pushBack(self.allocator, raw);
    }
};

fn lowestSetBit(mask: u32) u32 {
    if (mask == 0) return 0;
    return mask & (~mask +% 1);
}

fn parseProtocolError(packet: []const u8) ProtocolError {
    var tail: [20]u8 = undefined;
    @memcpy(tail[0..], packet[12..32]);
    return .{
        .code = packet[1],
        .sequence = std.mem.readInt(u16, packet[2..4], .native),
        .bad_value = std.mem.readInt(u32, packet[4..8], .native),
        .minor_opcode = std.mem.readInt(u16, packet[8..10], .native),
        .major_opcode = packet[10],
        .tail = tail,
    };
}
