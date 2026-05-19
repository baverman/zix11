const std = @import("std");
const extensions = @import("extensions.zig");
const render = @import("render.zig");
const shm = @import("shm.zig");
const xproto = @import("xproto.zig");

pub const ProtocolError = struct {
    code: u8,
    sequence: u16,
    bad_value: u32,
    minor_opcode: u16,
    major_opcode: u8,
    tail: [20]u8,
};

const ExtensionSpec = struct {
    ext: extensions.Extension,
    Error: type,
};

const extension_specs = .{
    ExtensionSpec{ .ext = .RENDER, .Error = render.Error },
    ExtensionSpec{ .ext = .MIT_SHM, .Error = shm.Error },
};

pub const TaggedErrorTag = buildTaggedErrorTag();
pub const TaggedError = buildTaggedError();

fn buildTaggedErrorTag() type {
    const count = comptime taggedErrorFieldCount();
    const Tag = tagIntType(count);
    comptime var names: [count][]const u8 = undefined;
    comptime var values: [count]Tag = undefined;
    comptime buildTaggedErrorNames(&names);
    for (&values, 0..) |*value, i| value.* = @intCast(i);
    return @Enum(Tag, .exhaustive, &names, &values);
}

fn buildTaggedError() type {
    const count = comptime taggedErrorFieldCount();
    comptime var names: [count][]const u8 = undefined;
    comptime var field_types: [count]type = undefined;
    comptime buildTaggedErrorNames(&names);
    comptime buildTaggedErrorTypes(&names, &field_types);
    return @Union(.auto, TaggedErrorTag, &names, &field_types, &@splat(.{}));
}

fn taggedErrorFieldCount() usize {
    comptime var count = 2;
    inline for (@typeInfo(xproto.Error).@"enum".fields) |field| {
        comptime if (std.mem.eql(u8, field.name, "_")) continue;
        count += 1;
    }
    inline for (extension_specs) |spec| {
        inline for (@typeInfo(spec.Error).@"enum".fields) |field| {
            comptime if (std.mem.eql(u8, field.name, "_")) continue;
            count += 1;
        }
    }
    return count;
}

fn buildTaggedErrorNames(
    names: anytype,
) void {
    comptime var i = 0;
    inline for (@typeInfo(xproto.Error).@"enum".fields) |field| {
        comptime if (std.mem.eql(u8, field.name, "_")) continue;
        names[i] = field.name;
        i += 1;
    }
    inline for (extension_specs) |spec| {
        inline for (@typeInfo(spec.Error).@"enum".fields) |field| {
            comptime if (std.mem.eql(u8, field.name, "_")) continue;
            names[i] = field.name;
            i += 1;
        }
    }
    names[i] = "Unknown";
    i += 1;
    names[i] = "NonX11";
}

fn buildTaggedErrorTypes(names: anytype, field_types: anytype) void {
    inline for (names, 0..) |name, i| {
        field_types[i] = if (std.mem.eql(u8, name, "NonX11")) anyerror else ProtocolError;
    }
}

fn tagIntType(comptime field_count: usize) type {
    return std.math.IntFittingRange(0, field_count - 1);
}

pub fn taggedError(
    registered_extensions: *const std.enums.EnumMap(extensions.Extension, ?extensions.ExtensionInfo),
    err: anyerror,
    raw: ProtocolError,
) TaggedError {
    if (err != error.X11ProtocolError) return .{ .NonX11 = err };
    if (decodeCore(raw)) |tagged| return tagged;
    if (decodeExtension(registered_extensions, raw)) |tagged| return tagged;
    return .{ .Unknown = raw };
}

fn decodeCore(raw: ProtocolError) ?TaggedError {
    return decodeEnumError(xproto.Error, raw.code, raw);
}

fn decodeExtension(
    registered_extensions: *const std.enums.EnumMap(extensions.Extension, ?extensions.ExtensionInfo),
    raw: ProtocolError,
) ?TaggedError {
    inline for (extension_specs) |spec| {
        if (registered_extensions.get(spec.ext)) |maybe_info| {
            if (maybe_info) |info| {
                if (raw.code >= info.first_error) {
                    const local_code = raw.code - info.first_error;
                    if (decodeEnumError(spec.Error, local_code, raw)) |tagged| return tagged;
                }
            }
        }
    }
    return null;
}

fn decodeEnumError(comptime E: type, code: u8, raw: ProtocolError) ?TaggedError {
    inline for (@typeInfo(E).@"enum".fields) |field| {
        comptime if (std.mem.eql(u8, field.name, "_")) continue;
        if (code == field.value) {
            return @unionInit(TaggedError, field.name, raw);
        }
    }
    return null;
}
