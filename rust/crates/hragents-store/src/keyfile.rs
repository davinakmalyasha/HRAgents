//! Per-install database key handling.
//!
//! The key is 32 random bytes. On Windows it is wrapped with DPAPI, so the
//! file cannot be opened by another Windows user or copied to another machine.
//! On macOS/Linux the file is written with mode 0600.
//!
//! The key file is deliberately kept out of database backups: a copied backup
//! alone cannot be decrypted. Losing the file means losing the database, which
//! is why setup must tell the operator to keep a recovery copy.

use crate::{StoreError, StoreResult};
use std::fs;
use std::io::{ErrorKind, Read, Write};
use std::path::{Path, PathBuf};

pub const KEY_FILE_NAME: &str = "hragents.key";
const KEY_LEN: usize = 32;
const SQLITE_HEADER: &[u8; 16] = b"SQLite format 3\0";

pub fn key_path(data_dir: &Path) -> PathBuf {
    data_dir.join(KEY_FILE_NAME)
}

/// True when the file is still a plaintext SQLite database.
pub fn is_plaintext_sqlite(path: &Path) -> StoreResult<bool> {
    let mut file = fs::File::open(path)
        .map_err(|error| StoreError::Key(format!("open {}: {error}", path.display())))?;
    let mut header = [0u8; 16];
    match file.read_exact(&mut header) {
        Ok(()) => Ok(&header == SQLITE_HEADER),
        Err(error) if error.kind() == ErrorKind::UnexpectedEof => Ok(false),
        Err(error) => Err(StoreError::Key(format!("read {}: {error}", path.display()))),
    }
}

/// Return the database key, creating one only when it is safe to do so.
///
/// If an encrypted database exists but its key file is gone, generate nothing:
/// a fresh key would silently make the data unrecoverable.
pub fn unlock_key_for(data_dir: &Path, db_path: &Path) -> StoreResult<String> {
    let path = key_path(data_dir);
    if path.exists() {
        return read_key(&path);
    }
    if db_path.exists() && !is_plaintext_sqlite(db_path)? {
        return Err(StoreError::Key(format!(
            "database {} is encrypted but {} is missing; restore the key file from a backup",
            db_path.display(),
            path.display()
        )));
    }
    create_key(&path)
}

pub fn read_key(path: &Path) -> StoreResult<String> {
    let stored = fs::read(path)
        .map_err(|error| StoreError::Key(format!("read key {}: {error}", path.display())))?;
    let raw = unprotect(&stored)?;
    if raw.len() != KEY_LEN {
        return Err(StoreError::Key(format!(
            "key file {} has {} bytes, expected {KEY_LEN}",
            path.display(),
            raw.len()
        )));
    }
    Ok(encode_hex(&raw))
}

fn create_key(path: &Path) -> StoreResult<String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| StoreError::Key(format!("create {}: {error}", parent.display())))?;
    }
    let mut raw = [0u8; KEY_LEN];
    getrandom::fill(&mut raw)
        .map_err(|error| StoreError::Key(format!("system random generator: {error}")))?;
    let stored = protect(&raw)?;

    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(path)
        .map_err(|error| StoreError::Key(format!("create key {}: {error}", path.display())))?;
    file.write_all(&stored)
        .and_then(|()| file.sync_all())
        .map_err(|error| StoreError::Key(format!("write key {}: {error}", path.display())))?;
    Ok(encode_hex(&raw))
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

#[cfg(windows)]
fn protect(raw: &[u8]) -> StoreResult<Vec<u8>> {
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CRYPT_INTEGER_BLOB, CRYPTPROTECT_UI_FORBIDDEN, CryptProtectData,
    };
    let input = CRYPT_INTEGER_BLOB {
        cbData: raw.len() as u32,
        pbData: raw.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    let ok = unsafe {
        CryptProtectData(
            &input,
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 {
        return Err(StoreError::Key(format!(
            "DPAPI protect failed: {}",
            std::io::Error::last_os_error()
        )));
    }
    let wrapped =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        LocalFree(output.pbData as _);
    }
    Ok(wrapped)
}

#[cfg(windows)]
fn unprotect(stored: &[u8]) -> StoreResult<Vec<u8>> {
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CRYPT_INTEGER_BLOB, CRYPTPROTECT_UI_FORBIDDEN, CryptUnprotectData,
    };
    let input = CRYPT_INTEGER_BLOB {
        cbData: stored.len() as u32,
        pbData: stored.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    let ok = unsafe {
        CryptUnprotectData(
            &input,
            std::ptr::null_mut(),
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 {
        return Err(StoreError::Key(format!(
            "DPAPI unprotect failed: {}",
            std::io::Error::last_os_error()
        )));
    }
    let raw = unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        LocalFree(output.pbData as _);
    }
    Ok(raw)
}

#[cfg(not(windows))]
fn protect(raw: &[u8]) -> StoreResult<Vec<u8>> {
    Ok(raw.to_vec())
}

#[cfg(not(windows))]
fn unprotect(stored: &[u8]) -> StoreResult<Vec<u8>> {
    Ok(stored.to_vec())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn key_is_created_once_and_reused() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("hragents.db");
        let first = unlock_key_for(dir.path(), &db).unwrap();
        let second = unlock_key_for(dir.path(), &db).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.len(), KEY_LEN * 2);
        assert!(key_path(dir.path()).exists());
    }

    #[test]
    fn missing_key_for_encrypted_file_fails_closed() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("hragents.db");
        std::fs::write(&db, b"not a plaintext sqlite header").unwrap();
        let error = unlock_key_for(dir.path(), &db).unwrap_err();
        assert!(error.to_string().contains("key file"), "{error}");
        assert!(!key_path(dir.path()).exists());
    }

    #[cfg(unix)]
    #[test]
    fn key_file_is_private() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("hragents.db");
        unlock_key_for(dir.path(), &db).unwrap();
        let mode = std::fs::metadata(key_path(dir.path()))
            .unwrap()
            .permissions()
            .mode()
            & 0o777;
        assert_eq!(mode, 0o600);
    }
}
