const std = @import("std");
const extensions = @import("extensions.zig");
const wire = @import("wire.zig");
const xproto = @import("xproto.zig");

const AuthName = "MIT-MAGIC-COOKIE-1";
const FamilyInternet: u16 = 0;
const FamilyLocal: u16 = 256;
const FamilyWild: u16 = 65535;
const read_buffer_size = 16 * 1024;
const write_buffer_size = 4 * 1024;

const DisplaySpec = struct {
    host: []u8,
    display_number: u16,

    fn deinit(self: @This(), allocator: std.mem.Allocator) void {
        allocator.free(self.host);
    }
};

pub const ProtocolError = struct {
    code: xproto.Error,
    sequence: u16,
    bad_value: u32,
    minor_opcode: u16,
    major_opcode: u8,
    tail: [20]u8,
};

pub const ReplyMode = enum {
    fixed,
    alloc,
    buffer,
};

pub const WriterReader = struct {
    writer: *std.Io.Writer,
    reader: *std.Io.Reader,
};

pub const StreamTransport = struct {
    io: std.Io,
    stream: std.Io.net.Stream,
    read_buffer: []u8,
    write_buffer: []u8,
    stream_reader: std.Io.net.Stream.Reader,
    stream_writer: std.Io.net.Stream.Writer,

    pub fn init(allocator: std.mem.Allocator, io: std.Io, stream: std.Io.net.Stream) !StreamTransport {
        const read_buffer = try allocator.alloc(u8, read_buffer_size);
        errdefer allocator.free(read_buffer);
        const write_buffer = try allocator.alloc(u8, write_buffer_size);
        errdefer allocator.free(write_buffer);

        return .{
            .io = io,
            .stream = stream,
            .read_buffer = read_buffer,
            .write_buffer = write_buffer,
            .stream_reader = stream.reader(io, read_buffer),
            .stream_writer = stream.writer(io, write_buffer),
        };
    }

    pub fn deinit(self: *@This(), allocator: std.mem.Allocator) void {
        self.stream.close(self.io);
        allocator.free(self.read_buffer);
        allocator.free(self.write_buffer);
    }

    pub fn wait(self: *const @This(), timeout_ms: i32) !bool {
        var pollfd = [1]std.posix.pollfd{.{
            .fd = self.fd(),
            .events = std.posix.POLL.IN,
            .revents = 0,
        }};
        const n = try std.posix.poll(&pollfd, timeout_ms);
        return n != 0;
    }

    pub fn fd(self: *const @This()) @TypeOf(self.stream.socket.handle) {
        return self.stream.socket.handle;
    }

    pub fn reader(self: *@This()) *std.Io.Reader {
        return &self.stream_reader.interface;
    }

    pub fn writer(self: *@This()) *std.Io.Writer {
        return &self.stream_writer.interface;
    }

    pub fn writer_reader(self: *@This()) WriterReader {
        return .{
            .writer = &self.stream_writer.interface,
            .reader = &self.stream_reader.interface,
        };
    }
};

pub const Connection = struct {
    allocator: std.mem.Allocator,
    proto: *Protocol,
    transport: *StreamTransport,
    root_window: xproto.Window,

    pub fn connectFromEnv(
        allocator: std.mem.Allocator,
        io: std.Io,
        environ_map: *const std.process.Environ.Map,
    ) !Connection {
        const display = environ_map.get("DISPLAY") orelse return error.MissingDisplay;
        const display_spec = try parseDisplay(allocator, display);
        defer display_spec.deinit(allocator);

        const cookie = try readXAuthorityCookie(io, allocator, environ_map, display_spec);
        defer allocator.free(cookie);

        return connect(allocator, io, cookie, display_spec);
    }

    pub fn connect(
        allocator: std.mem.Allocator,
        io: std.Io,
        cookie: []const u8,
        display: DisplaySpec,
    ) !Connection {
        if (display.host.len != 0) return error.RemoteDisplayUnsupported;

        const stream = try connectUnix(io, display.display_number);
        errdefer {
            var copy = stream;
            copy.close(io);
        }

        const proto = try allocator.create(Protocol);
        errdefer allocator.destroy(proto);
        proto.* = .init(allocator);
        errdefer proto.deinit();

        const transport = try allocator.create(StreamTransport);
        errdefer allocator.destroy(transport);
        transport.* = try .init(allocator, io, stream);
        errdefer transport.deinit(allocator);

        try proto.sendSetup(transport.writer(), cookie);
        try proto.readSetupReply(transport.reader());

        return .{
            .allocator = allocator,
            .proto = proto,
            .transport = transport,
            .root_window = proto.root_window,
        };
    }

    pub fn deinit(self: *@This()) void {
        self.proto.deinit();
        self.allocator.destroy(self.proto);

        self.transport.deinit(self.allocator);
        self.allocator.destroy(self.transport);

        self.* = undefined;
    }

    pub fn nextEvent(self: *Connection) !xproto.Event {
        if (try self.proto.pendingEvent()) |ev| return ev;
        return self.proto.readEvent(self.transport.reader());
    }

    pub fn waitForEvents(self: *Connection, timeout_ms: i32) !bool {
        if (self.hasPendingEvents()) return true;
        if (self.transport.reader().bufferedLen() != 0) return true;
        return self.transport.wait(timeout_ms);
    }

    pub fn pollEventTimeout(self: *Connection, timeout_ms: i32) !?xproto.Event {
        if (try self.proto.pendingEvent()) |ev| return ev;

        if (try self.waitForEvents(timeout_ms)) {
            return try self.proto.readEvent(self.transport.reader());
        }

        return null;
    }

    pub fn pollEvent(self: *Connection) !?xproto.Event {
        return self.pollEventTimeout(0);
    }

    pub fn request(self: *Connection, comptime Request: type, req: Request) !Request.Reply {
        return self.proto.requestWithStorage(self.transport.writer_reader(), Request, req, .fixed, {});
    }

    pub fn requestAlloc(self: *Connection, allocator: std.mem.Allocator, comptime Request: type, req: Request) !Request.Reply {
        return self.proto.requestWithStorage(self.transport.writer_reader(), Request, req, .alloc, allocator);
    }

    pub fn requestBuf(self: *Connection, buffer: []u8, comptime Request: type, req: Request) !Request.Reply {
        return self.proto.requestWithStorage(self.transport.writer_reader(), Request, req, .buffer, buffer);
    }

    pub fn allocId(self: *Connection, comptime T: type) !T {
        return self.proto.allocId(T);
    }

    pub fn lastError(self: *const Connection) ProtocolError {
        return self.proto.last_protocol_error orelse unreachable;
    }

    pub fn hasPendingEvents(self: *const Connection) bool {
        return self.proto.hasPendingEvents();
    }

    pub fn registerExtension(self: *Connection, ext: extensions.Extension) !void {
        return self.proto.registerExtension(self.transport.writer_reader(), ext);
    }
};

pub const Protocol = struct {
    allocator: std.mem.Allocator,
    root_window: xproto.Window,
    resource_id_base: u32,
    resource_id_mask: u32,
    resource_id_inc: u32,
    next_resource_id: u32,
    pending_events: std.Deque([32]u8),
    last_protocol_error: ?ProtocolError,
    sequence: u16 = 1,
    extensions: std.enums.EnumMap(extensions.Extension, ?extensions.ExtensionInfo),

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
            .extensions = std.enums.EnumMap(extensions.Extension, ?extensions.ExtensionInfo).initFull(null),
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
            @as(usize, std.mem.readInt(u32, header[4..8], .little)) * 4
        else
            0;
        const packet_len = 32 + extra_len;
        return try reader.take(packet_len);
    }

    fn readEvent(self: *Protocol, reader: *std.Io.Reader) !xproto.Event {
        while (true) {
            const packet = try self.readReplyPacket(reader);
            if (packet[0] == 0) {
                self.last_protocol_error = parseProtocolError(packet);
                continue;
            }
            var packet_reader: std.Io.Reader = .fixed(packet);
            return try xproto.decodeEvent(&packet_reader);
        }
    }

    pub fn pendingEvent(self: *Protocol) !?xproto.Event {
        if (self.pending_events.popFront()) |raw| {
            var packet_reader: std.Io.Reader = .fixed(&raw);
            return try xproto.decodeEvent(&packet_reader);
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
        const opcode = if (Request.extension) |ext| blk: {
            const maybe_info = self.extensions.get(ext) orelse return error.ExtensionNotRegistered;
            const info = maybe_info orelse return error.ExtensionNotRegistered;
            break :blk info.major_opcode;
        } else Request.opcode;

        try writer.writeByte(opcode);
        if (Request.extension == null) {
            try writer.writeByte(request_value.headerByte1());
        } else {
            try writer.writeByte(Request.opcode);
        }
        try writer.writeInt(u16, @intCast((len + pad) / 4), .little);
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

    pub fn registerExtension(self: *Protocol, wr: WriterReader, ext: extensions.Extension) !void {
        const reply = try self.requestWithStorage(wr, xproto.QueryExtension, .{
            .name = extensions.xname(ext),
        }, .fixed, .{});
        if (!reply.present) return error.ExtensionUnavailable;
        self.extensions.put(ext, .{
            .major_opcode = reply.major_opcode,
            .first_event = reply.first_event,
            .first_error = reply.first_error,
        });
    }

    pub fn sync(self: *Protocol, wr: WriterReader, request_sequence: u16) !void {
        const sync_sequence = try self.send(wr.writer, xproto.GetInputFocus{}, true);
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
                    const reply_sequence = std.mem.readInt(u16, packet[2..4], .little);
                    var packet_reader: std.Io.Reader = .fixed(packet);
                    const reply = try xproto.GetInputFocusReply.decode(&packet_reader);
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
        try (xproto.SetupRequest{
            .byte_order = 'l',
            .protocol_major_version = 11,
            .protocol_minor_version = 0,
            .authorization_protocol_name = AuthName,
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
                var setup = try xproto.Setup.decode(self.allocator, &packet_reader);
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
                var failed = try xproto.SetupFailed.decode(self.allocator, &packet_reader);
                defer failed.deinit(self.allocator);
                return error.X11SetupFailed;
            },
            2 => {
                var auth = try xproto.SetupAuthenticate.decode(self.allocator, &packet_reader);
                defer auth.deinit(self.allocator);
                return error.X11SetupAuthenticate;
            },
            else => return error.X11SetupUnknown,
        }
    }

    pub fn readSetupPacket(self: *const Protocol, reader: *std.Io.Reader) ![]const u8 {
        _ = self;
        const prefix = try reader.peek(8);
        const extra_len = @as(usize, std.mem.readInt(u16, prefix[6..8], .little)) * 4;
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

fn readXAuthorityCookie(
    io: std.Io,
    allocator: std.mem.Allocator,
    environ_map: *const std.process.Environ.Map,
    display: DisplaySpec,
) ![]u8 {
    const path = try xauthorityPath(allocator, environ_map);
    defer allocator.free(path);

    const contents = try std.Io.Dir.cwd().readFileAlloc(io, path, allocator, .limited(1024 * 1024));
    defer allocator.free(contents);

    const host_name = try localHostName(allocator);
    defer allocator.free(host_name);

    var offset: usize = 0;
    while (offset < contents.len) {
        const family = try readCountedU16(contents, &offset);
        const address = try readCountedSlice(contents, &offset);
        const number = try readCountedSlice(contents, &offset);
        const name = try readCountedSlice(contents, &offset);
        const data = try readCountedSlice(contents, &offset);

        if (!std.mem.eql(u8, name, AuthName)) continue;
        if (!matchDisplayNumber(display, number)) continue;
        if (!matchAuthorityAddress(display, family, address, host_name)) continue;

        return allocator.dupe(u8, data);
    }

    return error.XAuthorityCookieNotFound;
}

fn xauthorityPath(allocator: std.mem.Allocator, environ_map: *const std.process.Environ.Map) ![]u8 {
    if (environ_map.get("XAUTHORITY")) |path| {
        return allocator.dupe(u8, path);
    }

    const home = environ_map.get("HOME") orelse return error.MissingHome;
    return std.fmt.allocPrint(allocator, "{s}/.Xauthority", .{home});
}

fn localHostName(allocator: std.mem.Allocator) ![]u8 {
    var buffer: [std.posix.HOST_NAME_MAX]u8 = undefined;
    const host = try std.posix.gethostname(&buffer);
    return allocator.dupe(u8, host);
}

fn readCountedU16(buf: []const u8, offset: *usize) !u16 {
    if (offset.* + 2 > buf.len) return error.MalformedXAuthority;
    const value = std.mem.readInt(u16, buf[offset.*..][0..2], .big);
    offset.* += 2;
    return value;
}

fn readCountedSlice(buf: []const u8, offset: *usize) ![]const u8 {
    const len = try readCountedU16(buf, offset);
    if (offset.* + len > buf.len) return error.MalformedXAuthority;
    const out = buf[offset.* .. offset.* + len];
    offset.* += len;
    return out;
}

fn matchDisplayNumber(display: DisplaySpec, number: []const u8) bool {
    var display_buf: [16]u8 = undefined;
    const display_text = std.fmt.bufPrint(&display_buf, "{}", .{display.display_number}) catch return false;
    return std.mem.eql(u8, number, display_text);
}

fn matchAuthorityAddress(
    display: DisplaySpec,
    family: u16,
    address: []const u8,
    host_name: []const u8,
) bool {
    switch (family) {
        FamilyWild => return true,
        FamilyLocal => {
            if (display.host.len != 0) return false;
            return address.len == 0 or std.mem.eql(u8, address, host_name);
        },
        FamilyInternet => {
            if (display.host.len == 0) return false;
            return std.mem.eql(u8, address, display.host);
        },
        else => return false,
    }
}

fn parseDisplay(allocator: std.mem.Allocator, display: []const u8) !DisplaySpec {
    const colon = std.mem.indexOfScalar(u8, display, ':') orelse return error.UnsupportedDisplayFormat;
    const host = try allocator.dupe(u8, display[0..colon]);

    var tail = display[colon + 1 ..];
    if (tail.len == 0) return error.UnsupportedDisplayFormat;
    if (std.mem.indexOfScalar(u8, tail, '.')) |dot| tail = tail[0..dot];

    return .{
        .host = host,
        .display_number = try std.fmt.parseUnsigned(u16, tail, 10),
    };
}

fn connectUnix(io: std.Io, display_number: u16) !std.Io.net.Stream {
    var path_buf: [64]u8 = undefined;
    const path = try std.fmt.bufPrint(&path_buf, "/tmp/.X11-unix/X{}", .{display_number});
    const address = try std.Io.net.UnixAddress.init(path);
    return address.connect(io);
}

fn lowestSetBit(mask: u32) u32 {
    if (mask == 0) return 0;
    return mask & (~mask +% 1);
}

fn parseProtocolError(packet: []const u8) ProtocolError {
    var tail: [20]u8 = undefined;
    @memcpy(tail[0..], packet[12..32]);
    return .{
        .code = @enumFromInt(packet[1]),
        .sequence = std.mem.readInt(u16, packet[2..4], .little),
        .bad_value = std.mem.readInt(u32, packet[4..8], .little),
        .minor_opcode = std.mem.readInt(u16, packet[8..10], .little),
        .major_opcode = packet[10],
        .tail = tail,
    };
}
