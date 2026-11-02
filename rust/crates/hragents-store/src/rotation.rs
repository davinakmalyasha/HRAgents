//! Crash-safe install-key rotation.
//!
//! A sealed journal records the old and new keys before any data is touched.
//! The database is rekeyed first, documents are re-encrypted idempotently, and
//! the key file is swapped last. If the process stops at any point, the next
//! launch resumes from the journal (restoring the encrypted pre-rotation copy
//! if the database itself was interrupted mid-rekey).

use crate::{Store, StoreError, StoreResult, document_crypto, keyfile};
use hragents_core::audit::AuditActor;
use hragents_core::time::UtcInstant;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

const JOURNAL_FILE: &str = "hragents.rotate";
const DB_BACKUP_FILE: &str = "hragents.db.pre-rotate";

#[derive(Debug, Serialize, Deserialize)]
struct Journal {
    old_key: String,
    new_key: String,
    db_backup: String,
}

pub fn journal_path(data_dir: &Path) -> PathBuf {
    data_dir.join(JOURNAL_FILE)
}

fn backup_path(data_dir: &Path) -> PathBuf {
    data_dir.join(DB_BACKUP_FILE)
}

/// Copy the encrypted database and seal the journal. Must be called after a
/// WAL checkpoint and before `rekey`.
pub fn begin(data_dir: &Path, db_path: &Path, old_key: &str, new_key: &str) -> StoreResult<()> {
    if !keyfile::is_valid_key(old_key) || !keyfile::is_valid_key(new_key) {
        return Err(StoreError::Key(
            "rotation keys must be 64 hexadecimal characters".into(),
        ));
    }
    let backup = backup_path(data_dir);
    remove_file_if_exists(&backup)?;
    fs::copy(db_path, &backup)
        .map_err(|error| StoreError::Key(format!("copy pre-rotation database: {error}")))?;
    let journal = Journal {
        old_key: old_key.to_owned(),
        new_key: new_key.to_owned(),
        db_backup: DB_BACKUP_FILE.to_owned(),
    };
    keyfile::seal_file(
        &journal_path(data_dir),
        &serde_json::to_vec(&journal)
            .map_err(|error| StoreError::Key(format!("serialize journal: {error}")))?,
    )
}

/// Re-encrypt every document from the old key to the new one. Idempotent: files
/// already readable with the new key are left alone.
pub fn rotate_documents(
    documents_dir: &Path,
    old_key: Option<&[u8; 32]>,
    new_key: &[u8; 32],
) -> StoreResult<usize> {
    if !documents_dir.exists() {
        return Ok(0);
    }
    let mut rotated = 0usize;
    let entries = fs::read_dir(documents_dir)
        .map_err(|error| StoreError::Key(format!("read documents: {error}")))?;
    for entry in entries {
        let entry = entry.map_err(|error| StoreError::Key(format!("read entry: {error}")))?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let stored = fs::read(&path)
            .map_err(|error| StoreError::Key(format!("read {}: {error}", path.display())))?;
        let plaintext = if document_crypto::is_encrypted(&stored) {
            match document_crypto::decrypt(new_key, &stored) {
                Ok(_) => continue,
                Err(_) => {
                    let old_key = old_key.ok_or_else(|| {
                        StoreError::Key(format!(
                            "{} is encrypted with an unknown key",
                            path.display()
                        ))
                    })?;
                    document_crypto::decrypt(old_key, &stored).map_err(|_| {
                        StoreError::Key(format!(
                            "{} cannot be decrypted with either rotation key",
                            path.display()
                        ))
                    })?
                }
            }
        } else {
            // Legacy plaintext document: encrypt it with the new key.
            stored
        };
        let encrypted = document_crypto::encrypt(new_key, &plaintext)?;
        let staging = path.with_extension("rotate-tmp");
        fs::write(&staging, &encrypted)
            .map_err(|error| StoreError::Key(format!("write {}: {error}", staging.display())))?;
        fs::rename(&staging, &path)
            .map_err(|error| StoreError::Key(format!("replace {}: {error}", path.display())))?;
        rotated += 1;
    }
    Ok(rotated)
}

pub fn finish(data_dir: &Path) -> StoreResult<()> {
    // Remove the old-key backup first. If that fails, keep the journal so the
    // next launch retries instead of leaving a decryptable pre-rotation copy.
    remove_file_if_exists(&backup_path(data_dir))?;
    remove_file_if_exists(&journal_path(data_dir))
}

/// Resume an interrupted rotation. Returns the active key when a journal was
/// found and completed.
pub fn resume(data_dir: &Path, db_path: &Path) -> StoreResult<Option<String>> {
    let Some(raw) = keyfile::open_sealed_file(&journal_path(data_dir))? else {
        return Ok(None);
    };
    let journal: Journal = serde_json::from_slice(&raw)
        .map_err(|error| StoreError::Key(format!("parse rotation journal: {error}")))?;
    if !keyfile::is_valid_key(&journal.old_key) || !keyfile::is_valid_key(&journal.new_key) {
        return Err(StoreError::Key(
            "rotation journal contains an invalid key".into(),
        ));
    }
    let old_key = journal.old_key;
    let new_key = journal.new_key;

    let new_opens = Store::open_encrypted(db_path, &new_key).is_ok();
    if !new_opens {
        let old_opens = Store::open_encrypted(db_path, &old_key).is_ok();
        if old_opens {
            let mut store = Store::open_encrypted(db_path, &old_key)?;
            store.rekey(&new_key)?;
        } else {
            let backup = data_dir.join(&journal.db_backup);
            if !backup.exists() {
                return Err(StoreError::Key(
                    "rotation interrupted and the pre-rotation backup is missing".into(),
                ));
            }
            remove_sidecars(db_path)?;
            fs::copy(&backup, db_path)
                .map_err(|error| StoreError::Key(format!("restore pre-rotation db: {error}")))?;
            let mut store = Store::open_encrypted(db_path, &old_key)?;
            store.rekey(&new_key)?;
        }
    }

    let documents_dir = data_dir.join("documents");
    rotate_documents(
        &documents_dir,
        Some(&document_crypto::derive_key(&old_key)),
        &document_crypto::derive_key(&new_key),
    )?;
    keyfile::write_key(data_dir, &new_key)?;

    let mut store = Store::open_encrypted(db_path, &new_key)?;
    store.append_audit(
        &AuditActor::system("key-rotation-resume"),
        "security.key_rotation_resumed",
        "system",
        "install-key",
        serde_json::json!({"documents": true, "reauth": false}),
        UtcInstant::now(),
    )?;
    finish(data_dir)?;
    Ok(Some(new_key))
}

fn remove_sidecars(db_path: &Path) -> StoreResult<()> {
    for suffix in ["-wal", "-shm"] {
        remove_file_if_exists(&PathBuf::from(format!("{}{suffix}", db_path.display())))?;
    }
    Ok(())
}

fn remove_file_if_exists(path: &Path) -> StoreResult<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(StoreError::Key(format!(
            "remove {}: {error}",
            path.display()
        ))),
    }
}
