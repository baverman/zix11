const extensions = @import("_ext.zig");
const generated_errors = @import("gen/errors.zig");
const generated_events = @import("gen/events.zig");

pub const Extension = extensions.Extension;
pub const ExtensionInfo = struct {
    major_opcode: u8,
    first_event: u8,
    first_error: u8,
    error_spec: ?*const generated_errors.ExtensionErrorSpec = null,
    event_spec: ?*const generated_events.ExtensionEventSpec = null,
};
pub const render = @import("gen/render.zig");
pub const shm = @import("gen/shm.zig");
pub const shape = @import("gen/shape.zig");
pub const xfixes = @import("gen/xfixes.zig");

pub fn xname(ext: Extension) []const u8 {
    return switch (ext) {
        .CORE => unreachable,
        .RENDER => "RENDER",
        .MIT_SHM => "MIT-SHM",
        .SHAPE => "SHAPE",
        .XFIXES => "XFIXES",
    };
}
