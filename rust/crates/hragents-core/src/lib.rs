//! HRAgents desktop domain core.
//!
//! This crate is deliberately free of Tauri, SQLite, network, and UI
//! dependencies. Every rule that must be reproducible is here, synchronous and
//! testable in milliseconds. Infrastructure crates depend on this one, never the
//! other way round.

pub mod approvals;
pub mod audit;
pub mod auth;
pub mod compliance;
pub mod documents;
pub mod error;
pub mod growth;
pub mod hiring;
pub mod hiring_comms;
pub mod ids;
pub mod leave;
pub mod money;
pub mod offboarding;
pub mod password;
pub mod payroll;
pub mod people;
pub mod policy;
pub mod reminders;
pub mod time;

pub use error::{DomainError, DomainResult};
pub use money::Money;
pub use time::{BusinessDate, UtcInstant};

/// The only role this edition ships. Employee, manager, finance, recruiter,
/// candidate, and admin roles are server-edition concepts, not desktop ones.
#[derive(
    Debug,
    Clone,
    Copy,
    PartialEq,
    Eq,
    Hash,
    serde::Serialize,
    serde::Deserialize,
    schemars::JsonSchema,
)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    HrOperator,
}

impl Role {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::HrOperator => "hr_operator",
        }
    }
}

impl std::fmt::Display for Role {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}
