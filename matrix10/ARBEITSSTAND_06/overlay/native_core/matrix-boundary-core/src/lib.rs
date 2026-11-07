//! Native boundary source work. NOT a complete Rust Matrix10 implementation.
//! This library has no startup server, network client, database, global user
//! state, semantic keyword classifier, content filter or hidden fallback.

#![deny(unsafe_op_in_unsafe_fn)]

pub mod boundary;
pub mod consent;
pub mod restriction;
pub mod value;

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;
use value::{decode, encode, MAX_BYTES};

pub const ABI_VERSION: u32 = 3;

#[no_mangle]
pub extern "C" fn matrix_boundary_abi_version() -> u32 { ABI_VERSION }

/// Validate one private framed request; copy one framed response into caller memory.
/// Return bytes written, or -1 invalid pointers/lengths, -2 insufficient output
/// capacity, -3 internal codec error. Business violations are ordinary framed
/// responses with ok=false and their existing WriterError status/code.
///
/// # Safety
/// The caller must keep input readable for input_len and output writable for
/// output_capacity throughout the call. The two ranges must not overlap. These
/// conditions are met by the supplied ctypes bridge's two independent buffers.
/// No pointer is retained; no cross-language allocator/free pairing is needed.
#[no_mangle]
pub unsafe extern "C" fn matrix_boundary_check(
    input: *const u8,
    input_len: usize,
    output: *mut u8,
    output_capacity: usize,
) -> isize {
    if input.is_null() || output.is_null() || input_len == 0 || input_len > MAX_BYTES
        || output_capacity == 0 || output_capacity > MAX_BYTES {
        return -1;
    }
    // SAFETY: the embedding adapter promises the valid non-overlapping buffers
    // documented above. Bounds are checked before making a Rust slice.
    let bytes = unsafe { slice::from_raw_parts(input, input_len) };
    let result = catch_unwind(AssertUnwindSafe(|| {
        match decode(bytes) {
            Ok(request) => boundary::evaluate(&request),
            Err(e) => boundary::failure("NATIVE_FRAME_INVALID", e.0, 503),
        }
    }));
    let reply = match result {
        Ok(v) => v,
        Err(_) => boundary::failure("NATIVE_PANIC", "native boundary panicked; no write authorized", 503),
    };
    let encoded = match encode(&reply) { Ok(b) => b, Err(_) => return -3 };
    if encoded.len() > output_capacity { return -2; }
    // SAFETY: encoded is a live Rust Vec; output is a separate caller allocation
    // with enough checked capacity. No pointer escapes this function.
    unsafe { std::ptr::copy_nonoverlapping(encoded.as_ptr(), output, encoded.len()); }
    encoded.len() as isize
}

#[cfg(test)]
mod ffi_tests {
    use super::*;
    #[test]
    fn abi_is_fixed() { assert_eq!(matrix_boundary_abi_version(), 3); }
    #[test]
    fn null_pointer_is_rejected() {
        let mut out=[0u8;256];
        assert_eq!(unsafe { matrix_boundary_check(std::ptr::null(),1,out.as_mut_ptr(),out.len()) },-1);
    }
    #[test]
    fn malformed_frame_is_a_structured_failure() {
        let input=b"not a frame";
        let mut out=[0u8;4096];
        let n=unsafe { matrix_boundary_check(input.as_ptr(),input.len(),out.as_mut_ptr(),out.len()) };
        assert!(n>0);
        let v=decode(&out[..n as usize]).unwrap();
        assert_eq!(v.get("ok").boolean(),Some(false));
        assert_eq!(v.get("code").text(),Some("NATIVE_FRAME_INVALID"));
    }
    #[test]
    fn small_output_buffer_is_rejected() {
        let input=b"bad"; let mut out=[0u8;1];
        assert_eq!(unsafe { matrix_boundary_check(input.as_ptr(),input.len(),out.as_mut_ptr(),out.len()) },-2);
    }
}
