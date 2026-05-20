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

const queued_event_inline_cap = 64;

const QueuedEvent = union(enum) {
    fixed: struct {
        data: [queued_event_inline_cap]u8,
        len: usize,
    },
    dyn: []u8,
};

pub const Protocol = struct {
    allocator: std.mem.Allocator,
    root_window: x.Window,
    resource_id_base: u32,
    resource_id_mask: u32,
    resource_id_inc: u32,
    next_resource_id: u32,
    pending_events: std.Deque(QueuedEvent),
    event_packet_scratch: []u8,
    last_protocol_error: ?ProtocolError,
    sequence: u16 = 1,
    extensions: std.enums.EnumMap(ext.Extension, ext.ExtensionInfo),

    pub fn init(allocator: std.mem.Allocator) Protocol {
        var result: Protocol = .{
            .allocator = allocator,
            .root_window = @enumFromInt(0),
            .resource_id_base = 0,
            .resource_id_mask = 0,
            .resource_id_inc = 0,
            .next_resource_id = 0,
            .pending_events = .empty,
            .event_packet_scratch = &.{},
            .last_protocol_error = null,
            .extensions = .{},
        };
        result.extensions.put(.CORE, .{
            .major_opcode = 0,
            .first_event = 0,
            .first_error = 0,
            .error_spec = errors.errorSpec(.CORE),
            .event_spec = events.eventSpec(.CORE),
        });
        return result;
    }

    pub fn deinit(self: *Protocol) void {
        while (self.pending_events.popFront()) |event| {
            switch (event) {
                .fixed => {},
                .dyn => |packet| self.allocator.free(packet),
            }
        }
        self.pending_events.deinit(self.allocator);
        if (self.event_packet_scratch.len != 0) self.allocator.free(self.event_packet_scratch);
    }

    pub fn readReplyPacket(self: *Protocol, reader: *std.Io.Reader) ![]const u8 {
        _ = self;
        const header = try reader.peek(32);
        const packet_kind = header[0];
        const extra_len = if (packet_kind == 1 or (packet_kind & 0x7f) == 35)
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
            return try events.decodeEvent(&self.extensions, try self.normalizeEventPacket(packet));
        }
    }

    pub fn pendingEvent(self: *Protocol) !?events.Event {
        if (self.pending_events.popFront()) |queued| {
            return try events.decodeEvent(&self.extensions, try self.normalizeQueuedEventPacket(queued));
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
            .error_spec = errors.errorSpec(extension),
            .event_spec = events.eventSpec(extension),
        });
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
        if (packet.len <= queued_event_inline_cap) {
            var raw = std.mem.zeroes([queued_event_inline_cap]u8);
            @memcpy(raw[0..packet.len], packet);
            try self.pending_events.pushBack(self.allocator, .{
                .fixed = .{
                    .data = raw,
                    .len = packet.len,
                },
            });
            return;
        }
        try self.pending_events.pushBack(self.allocator, .{
            .dyn = try self.allocator.dupe(u8, packet),
        });
    }

    fn normalizeEventPacket(self: *Protocol, packet: []const u8) ![]const u8 {
        if (packet.len <= 32) return packet;
        return try self.copyEventPacketToScratch(packet);
    }

    fn normalizeQueuedEventPacket(self: *Protocol, event: QueuedEvent) ![]const u8 {
        return switch (event) {
            .fixed => |fixed| if (fixed.len <= 32)
                fixed.data[0..fixed.len]
            else
                try self.copyEventPacketToScratch(fixed.data[0..fixed.len]),
            .dyn => |packet| blk: {
                defer self.allocator.free(packet);
                break :blk try self.copyEventPacketToScratch(packet);
            },
        };
    }

    fn copyEventPacketToScratch(self: *Protocol, packet: []const u8) ![]const u8 {
        if (self.event_packet_scratch.len < packet.len) {
            if (self.event_packet_scratch.len == 0) {
                self.event_packet_scratch = try self.allocator.alloc(u8, packet.len);
            } else {
                self.event_packet_scratch = try self.allocator.realloc(self.event_packet_scratch, packet.len);
            }
        }
        @memcpy(self.event_packet_scratch[0..packet.len], packet);
        return self.event_packet_scratch[0..packet.len];
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
