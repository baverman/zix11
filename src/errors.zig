const std = @import("std");
const generated = @import("gen/errors.zig");
const low_level = @import("_errors.zig");
const ext = @import("ext.zig");

pub const EncodeError = low_level.EncodeError;
pub const DecodeError = low_level.DecodeError;
pub const AllocDecodeError = low_level.AllocDecodeError;
pub const BufferDecodeError = low_level.BufferDecodeError;

pub const ProtocolError = generated.ProtocolError;
pub const TaggedError = generated.TaggedError;
pub const ExtensionErrorSpec = generated.ExtensionErrorSpec;
pub const errorSpec = generated.errorSpec;

pub fn taggedError(
    registered_extensions: *std.enums.EnumMap(ext.Extension, ext.ExtensionInfo),
    err: anyerror,
    raw: ProtocolError,
) TaggedError {
    if (err != error.X11ProtocolError) return .{ .NonX11 = err };
    if (generated.decodeCoreError(raw.code, raw)) |tagged| return tagged;

    var it = registered_extensions.iterator();
    while (it.next()) |entry| {
        const info = entry.value;
        const spec = info.error_spec orelse continue;
        if (raw.code >= info.first_error and raw.code <= info.first_error + spec.max_error_num) {
            const local_code = raw.code - info.first_error;
            return spec.decode(local_code, raw) orelse .{ .Unknown = raw };
        }
    }

    return .{ .Unknown = raw };
}
