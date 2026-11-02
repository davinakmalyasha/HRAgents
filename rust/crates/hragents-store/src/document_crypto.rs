//! Document payload encryption and key derivation.
//!
//! The database key is a 64-hex passphrase. Documents use a separate 256-bit
//! ChaCha20-Poly1305 key derived from it, with a random nonce per file. The
//! magic prefix lets a legacy plaintext file be recognized and migrated.

use crate::StoreError;
use chacha20poly1305::aead::{Aead, KeyInit};
use chacha20poly1305::{ChaCha20Poly1305, Key, Nonce};
use sha2::{Digest, Sha256};

pub const MAGIC: &[u8; 4] = b"HRD1";
const NONCE_LEN: usize = 12;
const TAG_LEN: usize = 16;

pub fn derive_key(passphrase: &str) -> [u8; 32] {
    Sha256::digest(passphrase.as_bytes()).into()
}

pub fn is_encrypted(stored: &[u8]) -> bool {
    stored.starts_with(MAGIC)
}

pub fn encrypt(key: &[u8; 32], bytes: &[u8]) -> Result<Vec<u8>, StoreError> {
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key));
    let mut nonce = [0u8; NONCE_LEN];
    getrandom::fill(&mut nonce)
        .map_err(|error| StoreError::Key(format!("document nonce: {error}")))?;
    let ciphertext = cipher
        .encrypt(Nonce::from_slice(&nonce), bytes)
        .map_err(|_| StoreError::Key("encrypt document failed".into()))?;
    let mut out = Vec::with_capacity(MAGIC.len() + NONCE_LEN + ciphertext.len());
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&ciphertext);
    Ok(out)
}

/// Decrypt an encrypted document. A file without the magic prefix is treated
/// as legacy plaintext and returned unchanged.
pub fn decrypt(key: &[u8; 32], stored: &[u8]) -> Result<Vec<u8>, StoreError> {
    if !is_encrypted(stored) {
        return Ok(stored.to_vec());
    }
    if stored.len() < MAGIC.len() + NONCE_LEN + TAG_LEN {
        return Err(StoreError::Key("document ciphertext is truncated".into()));
    }
    let nonce = &stored[MAGIC.len()..MAGIC.len() + NONCE_LEN];
    let ciphertext = &stored[MAGIC.len() + NONCE_LEN..];
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key));
    cipher
        .decrypt(Nonce::from_slice(nonce), ciphertext)
        .map_err(|_| {
            StoreError::Key("document decryption failed: wrong key or tampered file".into())
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn document_round_trip_and_tamper_rejection() {
        let key = derive_key("a-install-key");
        let encrypted = encrypt(&key, b"top secret").unwrap();
        assert!(is_encrypted(&encrypted));
        assert_eq!(decrypt(&key, &encrypted).unwrap(), b"top secret");
        let mut tampered = encrypted;
        let last = tampered.len() - 1;
        tampered[last] ^= 1;
        assert!(decrypt(&key, &tampered).is_err());
        assert!(decrypt(&derive_key("another-key"), &tampered).is_err());
        assert_eq!(
            decrypt(&key, b"legacy plaintext").unwrap(),
            b"legacy plaintext"
        );
    }
}
