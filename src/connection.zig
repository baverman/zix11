const std = @import("std");
const errors = @import("errors.zig");
const events = @import("events.zig");
const ext = @import("ext.zig");
const protocol_mod = @import("protocol.zig");
const x = @import("gen/xproto.zig");

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

pub const ProtocolError = errors.ProtocolError;
pub const TaggedError = errors.TaggedError;

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

    pub fn writer_reader(self: *@This()) protocol_mod.WriterReader {
        return .{
            .writer = &self.stream_writer.interface,
            .reader = &self.stream_reader.interface,
        };
    }
};

pub const Connection = struct {
    allocator: std.mem.Allocator,
    proto: *protocol_mod.Protocol,
    transport: *StreamTransport,
    root_window: x.Window,

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

        const proto = try allocator.create(protocol_mod.Protocol);
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

    pub fn nextEvent(self: *Connection) !events.Event {
        if (try self.proto.pendingEvent()) |ev| return ev;
        return self.proto.readEvent(self.transport.reader());
    }

    pub fn waitForEvents(self: *Connection, timeout_ms: i32) !bool {
        if (self.hasPendingEvents()) return true;
        if (self.transport.reader().bufferedLen() != 0) return true;
        return self.transport.wait(timeout_ms);
    }

    pub fn pollEventTimeout(self: *Connection, timeout_ms: i32) !?events.Event {
        if (try self.proto.pendingEvent()) |ev| return ev;

        if (try self.waitForEvents(timeout_ms)) {
            return try self.proto.readEvent(self.transport.reader());
        }

        return null;
    }

    pub fn pollEvent(self: *Connection) !?events.Event {
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

    pub fn lastRawError(self: *const Connection) ProtocolError {
        return self.proto.last_protocol_error orelse unreachable;
    }

    pub fn lastError(self: *const Connection, err: anyerror) TaggedError {
        if (err != error.X11ProtocolError) return .{ .NonX11 = err };
        return errors.taggedError(&self.proto.extensions, err, self.lastRawError());
    }

    pub fn hasPendingEvents(self: *const Connection) bool {
        return self.proto.hasPendingEvents();
    }

    pub fn registerExtension(self: *Connection, extension: ext.Extension) !void {
        return self.proto.registerExtension(self.transport.writer_reader(), extension);
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
