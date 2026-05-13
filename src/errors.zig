const std = @import("std");

pub const EncodeError = std.Io.Writer.Error;
pub const DecodeError = std.Io.Reader.Error;
pub const AllocDecodeError = std.Io.Reader.Error || std.mem.Allocator.Error;
pub const BufferDecodeError = std.Io.Reader.Error || error{BufferTooSmall};
