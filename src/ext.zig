const extensions = @import("_ext.zig");

pub const Extension = extensions.Extension;
pub const ExtensionInfo = struct {
    major_opcode: u8,
    first_event: u8,
    first_error: u8,
};
pub const render = @import("gen/render.zig");
pub const shm = @import("gen/shm.zig");

pub fn xname(ext: Extension) []const u8 {
    return switch (ext) {
        .RENDER => "RENDER",
        .MIT_SHM => "MIT-SHM",
    };
}
