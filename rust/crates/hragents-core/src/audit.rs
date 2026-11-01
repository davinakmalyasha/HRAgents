use crate::ids::{AuditId, OperatorId};
use crate::time::UtcInstant;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ActorType {
    System,
    Agent,
    Human,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ActorProvenance {
    Authenticated,
    SystemJob,
    AgentTool,
    LegacyString,
}

/// The actor recorded on an audit entry. The desktop edition accepts only
/// authenticated humans and system jobs; `Agent` exists so historical entries
/// remain readable, and the command layer refuses it for new consequential acts.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct AuditActor {
    pub actor_type: ActorType,
    pub actor_id: String,
    pub display_name: Option<String>,
    pub provenance: ActorProvenance,
    pub role: Option<String>,
}

impl AuditActor {
    pub fn human(operator_id: OperatorId, display_name: impl Into<String>) -> Self {
        Self {
            actor_type: ActorType::Human,
            actor_id: operator_id.to_string(),
            display_name: Some(display_name.into()),
            provenance: ActorProvenance::Authenticated,
            role: Some("hr_operator".to_owned()),
        }
    }

    pub fn system(job: impl Into<String>) -> Self {
        Self {
            actor_type: ActorType::System,
            actor_id: job.into(),
            display_name: None,
            provenance: ActorProvenance::SystemJob,
            role: None,
        }
    }

    pub fn is_human(&self) -> bool {
        self.actor_type == ActorType::Human && self.provenance == ActorProvenance::Authenticated
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct AuditEntry {
    pub seq: i64,
    pub entry_id: AuditId,
    pub created_at: UtcInstant,
    pub actor: AuditActor,
    pub action: String,
    pub subject_type: String,
    pub subject_id: String,
    pub payload: Value,
    pub prev_hash: Option<String>,
    pub entry_hash: String,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum AuditError {
    #[error("audit chain is empty")]
    Empty,
    #[error("entry {seq} has sequence {actual}, expected {expected}")]
    Sequence {
        seq: i64,
        expected: i64,
        actual: i64,
    },
    #[error("entry {seq} prev_hash does not match the previous entry")]
    PrevHash { seq: i64 },
    #[error("entry {seq} hash does not match its content")]
    Hash { seq: i64 },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AuditVerification {
    pub entries: usize,
    pub head_hash: Option<String>,
}

/// Canonical JSON: compact, keys sorted, no floats (money is integer sen).
///
/// Python uses `json.dumps(sort_keys=True, separators=(",", ":"),
/// ensure_ascii=False)`; `serde_json`'s default map is a `BTreeMap`, so object
/// keys are already ordered. Callers must not put floating-point values in an
/// audit payload: their shortest representation is not guaranteed identical
/// across runtimes, and a hash chain cannot tolerate that ambiguity.
pub fn canonical_json(value: &Value) -> Result<String, serde_json::Error> {
    serde_json::to_string(value)
}

pub fn payload_digest(value: &Value) -> Result<String, serde_json::Error> {
    Ok(hex_sha256(canonical_json(value)?.as_bytes()))
}

pub fn hex_sha256(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// Python `datetime.isoformat()` for a UTC instant, e.g.
/// `2026-11-01T09:00:00.123456+00:00`. Kept byte-compatible so a chain exported
/// from the Python oracle can be verified by the Rust implementation.
pub fn python_isoformat(instant: UtcInstant) -> String {
    instant
        .datetime()
        .format("%Y-%m-%dT%H:%M:%S%.6f+00:00")
        .to_string()
}

impl AuditEntry {
    #[allow(clippy::too_many_arguments)]
    pub fn compute_hash(
        prev_hash: Option<&str>,
        actor: &AuditActor,
        action: &str,
        subject_type: &str,
        subject_id: &str,
        payload: &Value,
        created_at: UtcInstant,
    ) -> Result<String, serde_json::Error> {
        let material = serde_json::json!({
            "prev_hash": prev_hash,
            "actor": actor,
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": payload,
            "created_at": python_isoformat(created_at),
        });
        payload_digest(&material)
    }

    pub fn verify(&self, previous: Option<&AuditEntry>) -> Result<(), AuditError> {
        let expected_prev = previous.map(|entry| entry.entry_hash.as_str());
        if self.prev_hash.as_deref() != expected_prev {
            return Err(AuditError::PrevHash { seq: self.seq });
        }
        let expected = Self::compute_hash(
            self.prev_hash.as_deref(),
            &self.actor,
            &self.action,
            &self.subject_type,
            &self.subject_id,
            &self.payload,
            self.created_at,
        )
        .map_err(|_| AuditError::Hash { seq: self.seq })?;
        if expected != self.entry_hash {
            return Err(AuditError::Hash { seq: self.seq });
        }
        Ok(())
    }
}

/// Append-only in-memory chain. The SQLite store persists the same rows and
/// verifies on startup; this type is the deterministic rule they share.
#[derive(Debug, Default, Clone)]
pub struct AuditChain {
    entries: Vec<AuditEntry>,
}

impl AuditChain {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn from_entries(entries: Vec<AuditEntry>) -> Result<Self, AuditError> {
        let chain = Self { entries };
        chain.verify()?;
        Ok(chain)
    }

    pub fn entries(&self) -> &[AuditEntry] {
        &self.entries
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn head_hash(&self) -> Option<&str> {
        self.entries.last().map(|entry| entry.entry_hash.as_str())
    }

    pub fn append(
        &mut self,
        actor: AuditActor,
        action: impl Into<String>,
        subject_type: impl Into<String>,
        subject_id: impl Into<String>,
        payload: Value,
        created_at: UtcInstant,
    ) -> Result<&AuditEntry, serde_json::Error> {
        let action = action.into();
        let subject_type = subject_type.into();
        let subject_id = subject_id.into();
        let prev_hash = self.head_hash().map(str::to_owned);
        let entry_hash = AuditEntry::compute_hash(
            prev_hash.as_deref(),
            &actor,
            &action,
            &subject_type,
            &subject_id,
            &payload,
            created_at,
        )?;
        let entry = AuditEntry {
            seq: self.entries.len() as i64,
            entry_id: AuditId::new(),
            created_at,
            actor,
            action,
            subject_type,
            subject_id,
            payload,
            prev_hash,
            entry_hash,
        };
        self.entries.push(entry);
        Ok(self.entries.last().expect("just pushed"))
    }

    pub fn verify(&self) -> Result<AuditVerification, AuditError> {
        for (index, entry) in self.entries.iter().enumerate() {
            if entry.seq != index as i64 {
                return Err(AuditError::Sequence {
                    seq: entry.seq,
                    expected: index as i64,
                    actual: entry.seq,
                });
            }
            entry.verify(index.checked_sub(1).map(|i| &self.entries[i]))?;
        }
        Ok(AuditVerification {
            entries: self.entries.len(),
            head_hash: self.head_hash().map(str::to_owned),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ids::OperatorId;

    fn actor() -> AuditActor {
        AuditActor::human(OperatorId::from_uuid(uuid::Uuid::nil()), "Rina")
    }

    #[test]
    fn chain_appends_and_verifies() {
        let mut chain = AuditChain::new();
        chain
            .append(
                actor(),
                "employee.created",
                "employee",
                "e1",
                serde_json::json!({"name": "Ayu"}),
                UtcInstant::from_millis(1_760_000_000_000).unwrap(),
            )
            .unwrap();
        chain
            .append(
                actor(),
                "employee.updated",
                "employee",
                "e1",
                serde_json::json!({"field": "phone"}),
                UtcInstant::from_millis(1_760_000_001_000).unwrap(),
            )
            .unwrap();
        let verification = chain.verify().unwrap();
        assert_eq!(verification.entries, 2);
        assert_eq!(verification.head_hash, chain.head_hash().map(str::to_owned));
    }

    #[test]
    fn tampering_breaks_the_chain() {
        let mut chain = AuditChain::new();
        chain
            .append(
                actor(),
                "employee.created",
                "employee",
                "e1",
                serde_json::json!({"name": "Ayu"}),
                UtcInstant::from_millis(1_760_000_000_000).unwrap(),
            )
            .unwrap();
        chain
            .append(
                actor(),
                "employee.updated",
                "employee",
                "e1",
                serde_json::json!({"field": "phone"}),
                UtcInstant::from_millis(1_760_000_001_000).unwrap(),
            )
            .unwrap();
        chain.entries[0].payload = serde_json::json!({"name": "Not Ayu"});
        assert_eq!(chain.verify(), Err(AuditError::Hash { seq: 0 }));
    }

    #[test]
    fn sequence_gap_is_detected() {
        let mut chain = AuditChain::new();
        chain
            .append(
                actor(),
                "x",
                "y",
                "z",
                Value::Null,
                UtcInstant::from_millis(0).unwrap(),
            )
            .unwrap();
        chain.entries[0].seq = 4;
        assert!(matches!(chain.verify(), Err(AuditError::Sequence { .. })));
    }

    #[test]
    fn python_isoformat_is_stable() {
        let instant = UtcInstant::from_millis(1_760_000_000_123).unwrap();
        assert_eq!(
            python_isoformat(instant),
            "2025-10-09T08:53:20.123000+00:00"
        );
    }
}
