const std = @import("std");
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

pub const Connection = struct {
    allocator: std.mem.Allocator,
    io: std.Io,
    stream: std.Io.net.Stream,
    read_buffer: []u8,
    write_buffer: []u8,
    stream_reader: std.Io.net.Stream.Reader,
    stream_writer: std.Io.net.Stream.Writer,
    root_window: xproto.Window,
    sequence: u16 = 1,

    pub fn connectFromInit(init: std.process.Init, allocator: std.mem.Allocator) !Connection {
        const display = init.environ_map.get("DISPLAY") orelse return error.MissingDisplay;
        const display_spec = try parseDisplay(allocator, display);
        defer display_spec.deinit(allocator);

        const cookie = try readXAuthorityCookie(init, allocator, display_spec);
        defer allocator.free(cookie);

        return connect(allocator, init.io, cookie, display_spec);
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

        const read_buffer = try allocator.alloc(u8, read_buffer_size);
        errdefer allocator.free(read_buffer);
        const write_buffer = try allocator.alloc(u8, write_buffer_size);
        errdefer allocator.free(write_buffer);

        var conn = Connection{
            .allocator = allocator,
            .io = io,
            .stream = stream,
            .read_buffer = read_buffer,
            .write_buffer = write_buffer,
            .stream_reader = stream.reader(io, read_buffer),
            .stream_writer = stream.writer(io, write_buffer),
            .root_window = @enumFromInt(0),
        };
        errdefer conn.deinit();

        try conn.sendSetup(cookie);
        try conn.readSetupReply();
        return conn;
    }

    pub fn deinit(self: *Connection) void {
        self.stream.close(self.io);
        self.allocator.free(self.read_buffer);
        self.allocator.free(self.write_buffer);
    }

    pub fn reader(self: *Connection) *std.Io.Reader {
        return &self.stream_reader.interface;
    }

    pub fn writer(self: *Connection) *std.Io.Writer {
        return &self.stream_writer.interface;
    }

    pub fn readReplyPacket(self: *Connection) ![]const u8 {
        const header = try self.reader().peek(32);
        const packet_kind = header[0];
        const extra_len = if (packet_kind == 1)
            @as(usize, std.mem.readInt(u32, header[4..8], .little)) * 4
        else
            0;
        const packet_len = 32 + extra_len;
        return try self.reader().take(packet_len);
    }

    pub fn send(self: *Connection, request_value: anytype) !u16 {
        const sequence = self.sequence;
        self.sequence +%= 1;
        try request_value.encode(self.writer());
        try self.writer().flush();
        return sequence;
    }

    pub fn request(self: *Connection, request_value: anytype) !@TypeOf(request_value).Reply {
        _ = try self.send(request_value);
        const packet = try self.readReplyPacket();
        var packet_reader: std.Io.Reader = .fixed(packet);
        return try @TypeOf(request_value).Reply.decode(&packet_reader);
    }

    pub fn requestAlloc(
        self: *Connection,
        allocator: std.mem.Allocator,
        request_value: anytype,
    ) !@TypeOf(request_value).Reply {
        _ = try self.send(request_value);
        const packet = try self.readReplyPacket();
        var packet_reader: std.Io.Reader = .fixed(packet);
        return try @TypeOf(request_value).Reply.decode(allocator, &packet_reader);
    }

    pub fn requestBuf(
        self: *Connection,
        request_value: anytype,
        scratch: []u8,
    ) !@TypeOf(request_value).Reply {
        _ = try self.send(request_value);
        const packet = try self.readReplyPacket();
        var packet_reader: std.Io.Reader = .fixed(packet);
        return try @TypeOf(request_value).Reply.decode(&packet_reader, scratch);
    }

    fn sendSetup(self: *Connection, cookie: []const u8) !void {
        try (xproto.SetupRequest{
            .byte_order = 'l',
            .protocol_major_version = 11,
            .protocol_minor_version = 0,
            .authorization_protocol_name = AuthName,
            .authorization_protocol_data = cookie,
        }).encode(self.writer());
        try self.writer().flush();
    }

    fn readSetupReply(self: *Connection) !void {
        const packet = try self.readSetupPacket();
        const status = packet[0];
        var packet_reader: std.Io.Reader = .fixed(packet);
        switch (status) {
            1 => {
                var setup = try xproto.Setup.decode(self.allocator, &packet_reader);
                defer setup.deinit(self.allocator);
                if (setup.roots.len == 0) return error.MalformedPacket;
                const screen = setup.roots[0];
                self.root_window = screen.root;
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

    fn readSetupPacket(self: *Connection) ![]const u8 {
        const prefix = try self.reader().peek(8);
        const extra_len = @as(usize, std.mem.readInt(u16, prefix[6..8], .little)) * 4;
        const packet_len = 8 + extra_len;
        return try self.reader().take(packet_len);
    }
};

fn readXAuthorityCookie(
    init: std.process.Init,
    allocator: std.mem.Allocator,
    display: DisplaySpec,
) ![]u8 {
    const path = try xauthorityPath(init, allocator);
    defer allocator.free(path);

    const contents = try std.Io.Dir.cwd().readFileAlloc(init.io, path, allocator, .limited(1024 * 1024));
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

fn xauthorityPath(init: std.process.Init, allocator: std.mem.Allocator) ![]u8 {
    if (init.environ_map.get("XAUTHORITY")) |path| {
        return allocator.dupe(u8, path);
    }

    const home = init.environ_map.get("HOME") orelse return error.MissingHome;
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
