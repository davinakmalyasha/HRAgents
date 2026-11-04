use argon2::password_hash::phc::PasswordHash;
use argon2::{Argon2, PasswordHasher, PasswordVerifier};
use rand::RngCore;

#[derive(Debug, thiserror::Error)]
pub enum PasswordError {
    #[error("password hashing failed")]
    Hash,
    #[error("stored password hash is invalid")]
    InvalidHash,
    #[error("password must be at least 12 characters")]
    TooShort,
}

/// Argon2id with the parameters fixed by ADR-0012. Parameters are encoded in
/// the PHC string, so raising them later still verifies old hashes and rehashes
/// on the next successful login.
pub fn hash_password(password: &str) -> Result<String, PasswordError> {
    if password.chars().count() < 12 {
        return Err(PasswordError::TooShort);
    }
    let mut salt = [0_u8; 16];
    rand::rng().fill_bytes(&mut salt);
    Argon2::default()
        .hash_password_with_salt(password.as_bytes(), &salt)
        .map(|hash| hash.to_string())
        .map_err(|_| PasswordError::Hash)
}

pub fn verify_password(hash: &str, password: &str) -> Result<bool, PasswordError> {
    let parsed = PasswordHash::new(hash).map_err(|_| PasswordError::InvalidHash)?;
    Ok(Argon2::default()
        .verify_password(password.as_bytes(), &parsed)
        .is_ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hashes_and_verifies() {
        let hash = hash_password("correct horse battery staple").unwrap();
        assert!(verify_password(&hash, "correct horse battery staple").unwrap());
        assert!(!verify_password(&hash, "wrong password").unwrap());
        assert!(hash.starts_with("$argon2id$"));
    }

    #[test]
    fn rejects_short_passwords() {
        assert!(matches!(
            hash_password("short"),
            Err(PasswordError::TooShort)
        ));
    }
}
