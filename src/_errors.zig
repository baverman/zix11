const std = @import("std");

pub const EncodeError = std.Io.Writer.Error;
pub const DecodeError = std.Io.Reader.Error || error{UnexpectedSwitchTag};
pub const AllocDecodeError = DecodeError || std.mem.Allocator.Error;
pub const BufferDecodeError = DecodeError || error{BufferTooSmall};
