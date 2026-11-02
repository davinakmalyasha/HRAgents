//! Encrypted backup set: database, uploaded documents, and the key file.
//!
//! The archive is a plain ZIP container (no meaningful compression on
//! ciphertext). Every member is hashed in `manifest.json`, and restore verifies
//! hashes before opening the database. The key file is OS-protected; on another
//! machine restore with the exported recovery key instead.

use crate::{AppError, AppResult};
use hragents_store::{Store, keyfile};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

pub const FORMAT: &str = "hragents-backup-set/1";
const MANIFEST: &str = "manifest.json";
const DB_MEMBER: &str = "hragents.db";
const KEY_MEMBER: &str = "hragents.key";
const DOCS_PREFIX: &str = "documents/";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    pub format: String,
    pub created_at_ms: i64,
    pub schema_version: i64,
    pub audit_entries: usize,
    pub key_included: bool,
    pub documents: usize,
    pub files: BTreeMap<String, String>,
}

pub fn create(
    archive: &Path,
    db: &Path,
    documents_dir: &Path,
    key_file: Option<&Path>,
    key_override: Option<&str>,
) -> AppResult<u64> {
    if !db.exists() {
        return Err(AppError::Export(format!(
            "database not found: {}",
            db.display()
        )));
    }
    let staging = archive.with_extension("hrbackup-tmp");
    remove_if_exists(&staging)?;

    let mut sources: Vec<(String, PathBuf)> = vec![(DB_MEMBER.to_owned(), db.to_path_buf())];
    if let Some(key_file) = key_file.filter(|path| path.exists()) {
        sources.push((KEY_MEMBER.to_owned(), key_file.to_path_buf()));
    }
    let mut documents = 0usize;
    if documents_dir.is_dir() {
        let entries = fs::read_dir(documents_dir)
            .map_err(|error| AppError::Export(format!("read documents: {error}")))?;
        for entry in entries {
            let entry = entry.map_err(|error| AppError::Export(format!("read entry: {error}")))?;
            let path = entry.path();
            if !path.is_file() {
                continue;
            }
            let name = path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| AppError::Export("document name is not UTF-8".into()))?;
            sources.push((format!("{DOCS_PREFIX}{name}"), path));
            documents += 1;
        }
    }

    let mut files = BTreeMap::new();
    for (name, path) in &sources {
        files.insert(name.clone(), sha256_file(path)?);
    }
    let key = match key_override {
        Some(key) => Some(key.to_owned()),
        None => key_file
            .filter(|path| path.exists())
            .map(keyfile::read_key)
            .transpose()?,
    };
    let store = match key.as_deref() {
        Some(key) => Store::open_encrypted(db, key)?,
        None => Store::open(db)?,
    };
    store.checkpoint()?;
    let manifest = Manifest {
        format: FORMAT.into(),
        created_at_ms: hragents_core::time::UtcInstant::now().millis(),
        schema_version: store.schema_version()?,
        audit_entries: store.verify_audit()?.entries,
        key_included: key_file.is_some_and(Path::exists),
        documents,
        files,
    };
    drop(store);

    let file = fs::File::create(&staging)
        .map_err(|error| AppError::Export(format!("create backup set: {error}")))?;
    let mut zip = zip::ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Stored)
        .unix_permissions(0o600);
    zip.start_file(MANIFEST, options)
        .map_err(|error| AppError::Export(format!("write manifest: {error}")))?;
    zip.write_all(
        &serde_json::to_vec_pretty(&manifest)
            .map_err(|error| AppError::Export(format!("serialize manifest: {error}")))?,
    )
    .map_err(|error| AppError::Export(format!("write manifest: {error}")))?;
    for (name, path) in &sources {
        zip.start_file(name.as_str(), options)
            .map_err(|error| AppError::Export(format!("add {name}: {error}")))?;
        let mut source = fs::File::open(path)
            .map_err(|error| AppError::Export(format!("open {name}: {error}")))?;
        std::io::copy(&mut source, &mut zip)
            .map_err(|error| AppError::Export(format!("copy {name}: {error}")))?;
    }
    zip.finish()
        .map_err(|error| AppError::Export(format!("finish backup set: {error}")))?;
    fs::rename(&staging, archive)
        .map_err(|error| AppError::Export(format!("install backup set: {error}")))?;
    Ok(fs::metadata(archive)
        .map_err(|error| AppError::Export(format!("stat backup set: {error}")))?
        .len())
}

pub fn restore(archive: &Path, dest: &Path, key_override: Option<&str>) -> AppResult<Manifest> {
    if dest.exists() {
        return Err(AppError::Export(format!(
            "restore destination already exists: {}",
            dest.display()
        )));
    }
    let staging = dest.with_extension("restore-staging");
    remove_dir_if_exists(&staging)?;
    fs::create_dir_all(&staging)
        .map_err(|error| AppError::Export(format!("create staging: {error}")))?;

    let file = fs::File::open(archive)
        .map_err(|error| AppError::Export(format!("open backup set: {error}")))?;
    let mut zip = zip::ZipArchive::new(file)
        .map_err(|error| AppError::Export(format!("read backup set: {error}")))?;
    let manifest: Manifest = {
        let mut manifest = zip
            .by_name(MANIFEST)
            .map_err(|error| AppError::Export(format!("manifest missing: {error}")))?;
        let mut raw = String::new();
        manifest
            .read_to_string(&mut raw)
            .map_err(|error| AppError::Export(format!("read manifest: {error}")))?;
        serde_json::from_str(&raw)
            .map_err(|error| AppError::Export(format!("parse manifest: {error}")))?
    };
    if manifest.format != FORMAT {
        return Err(AppError::Export(format!(
            "unsupported backup format {}",
            manifest.format
        )));
    }
    for (name, expected) in &manifest.files {
        if !valid_member_name(name) {
            return Err(AppError::Export(format!("unexpected backup member {name}")));
        }
        let mut member = zip
            .by_name(name)
            .map_err(|error| AppError::Export(format!("member {name} missing: {error}")))?;
        let output = staging.join(name);
        if let Some(parent) = output.parent() {
            fs::create_dir_all(parent).map_err(|error| {
                AppError::Export(format!("create {}: {error}", parent.display()))
            })?;
        }
        let mut handle = fs::File::create(&output)
            .map_err(|error| AppError::Export(format!("write {name}: {error}")))?;
        let mut hasher = Sha256::new();
        let mut buffer = [0u8; 64 * 1024];
        loop {
            let read = member
                .read(&mut buffer)
                .map_err(|error| AppError::Export(format!("read {name}: {error}")))?;
            if read == 0 {
                break;
            }
            hasher.update(&buffer[..read]);
            handle
                .write_all(&buffer[..read])
                .map_err(|error| AppError::Export(format!("write {name}: {error}")))?;
        }
        let actual = encode_hex(&hasher.finalize());
        if &actual != expected {
            return Err(AppError::Export(format!(
                "hash mismatch for {name}: expected {expected}, got {actual}"
            )));
        }
    }

    let db = staging.join(DB_MEMBER);
    let key_file = staging.join(KEY_MEMBER);
    let key = match key_override {
        Some(key) => Some(key.to_owned()),
        None if key_file.exists() => Some(keyfile::read_key(&key_file).map_err(|error| {
            AppError::Export(format!(
                "{error}; restore with the exported recovery key instead"
            ))
        })?),
        None => None,
    };
    let store = match key.as_deref() {
        Some(key) => Store::open_encrypted(&db, key)?,
        None => Store::open(&db)?,
    };
    if store.integrity_check()? != "ok" {
        return Err(AppError::Export(
            "restored database integrity failed".into(),
        ));
    }
    let entries = store.verify_audit()?.entries;
    if entries != manifest.audit_entries {
        return Err(AppError::Export(format!(
            "audit entries changed: manifest {}, restored {entries}",
            manifest.audit_entries
        )));
    }
    drop(store);
    fs::rename(&staging, dest)
        .map_err(|error| AppError::Export(format!("install restored data: {error}")))?;
    Ok(manifest)
}

fn valid_member_name(name: &str) -> bool {
    if name == DB_MEMBER || name == KEY_MEMBER {
        return true;
    }
    let Some(document) = name.strip_prefix(DOCS_PREFIX) else {
        return false;
    };
    !document.is_empty()
        && document != "."
        && document != ".."
        && !document.contains('/')
        && !document.contains('\\')
}

fn sha256_file(path: &Path) -> AppResult<String> {
    let mut file =
        fs::File::open(path).map_err(|error| AppError::Export(format!("open file: {error}")))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| AppError::Export(format!("read file: {error}")))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(encode_hex(&hasher.finalize()))
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

fn remove_if_exists(path: &Path) -> AppResult<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(AppError::Export(format!(
            "remove {}: {error}",
            path.display()
        ))),
    }
}

fn remove_dir_if_exists(path: &Path) -> AppResult<()> {
    match fs::remove_dir_all(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(AppError::Export(format!(
            "remove {}: {error}",
            path.display()
        ))),
    }
}
