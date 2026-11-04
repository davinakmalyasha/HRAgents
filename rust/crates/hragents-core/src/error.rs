use crate::money::MoneyError;

#[derive(Debug, thiserror::Error)]
pub enum DomainError {
    #[error("{message}")]
    Validation { code: &'static str, message: String },
    #[error("{entity} not found: {id}")]
    NotFound { entity: &'static str, id: String },
    #[error("{message}")]
    Conflict { code: &'static str, message: String },
    #[error("authentication required")]
    Unauthenticated,
    #[error("this action requires a fresh re-authentication")]
    ReauthRequired,
    #[error("the operator is not permitted to perform this action")]
    Forbidden,
    #[error("{message}")]
    RateTableUnverified { message: String },
    #[error("invariant violated: {0}")]
    Invariant(String),
    #[error(transparent)]
    Money(#[from] MoneyError),
    #[error("invalid state transition from {from} to {to}")]
    Transition { from: String, to: String },
}

impl DomainError {
    pub fn validation(code: &'static str, message: impl Into<String>) -> Self {
        Self::Validation {
            code,
            message: message.into(),
        }
    }

    pub fn conflict(code: &'static str, message: impl Into<String>) -> Self {
        Self::Conflict {
            code,
            message: message.into(),
        }
    }

    pub fn invariant(message: impl Into<String>) -> Self {
        Self::Invariant(message.into())
    }

    /// Stable machine code surfaced to the UI. Never a Rust error string.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Validation { code, .. } => code,
            Self::NotFound { .. } => "E_NOT_FOUND",
            Self::Conflict { code, .. } => code,
            Self::Unauthenticated => "E_UNAUTHENTICATED",
            Self::ReauthRequired => "E_REAUTH_REQUIRED",
            Self::Forbidden => "E_FORBIDDEN",
            Self::RateTableUnverified { .. } => "E_RATE_TABLE_UNVERIFIED",
            Self::Invariant(_) => "E_INVARIANT",
            Self::Money(_) => "E_MONEY",
            Self::Transition { .. } => "E_TRANSITION",
        }
    }
}

pub type DomainResult<T> = Result<T, DomainError>;
