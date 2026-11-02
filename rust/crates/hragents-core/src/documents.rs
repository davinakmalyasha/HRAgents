use crate::error::{DomainError, DomainResult};
use crate::ids::{DocumentId, DocumentRequestId, EmployeeId};
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum DocumentRequestStatus {
    Requested,
    Uploaded,
    Verified,
    Rejected,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct DocumentRequest {
    pub id: DocumentRequestId,
    pub employee_id: EmployeeId,
    pub document_type: String,
    pub status: DocumentRequestStatus,
    pub requested_at: UtcInstant,
    pub due_on: Option<BusinessDate>,
    pub document_id: Option<DocumentId>,
    pub note: Option<String>,
}

impl DocumentRequest {
    pub fn new(
        employee_id: EmployeeId,
        document_type: impl Into<String>,
        due_on: Option<BusinessDate>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        let document_type = document_type.into();
        if document_type.trim().len() < 2 {
            return Err(DomainError::validation(
                "E_DOCUMENT_TYPE",
                "a document request needs a document type",
            ));
        }
        Ok(Self {
            id: DocumentRequestId::new(),
            employee_id,
            document_type,
            status: DocumentRequestStatus::Requested,
            requested_at: now,
            due_on,
            document_id: None,
            note: None,
        })
    }

    pub fn attach(&mut self, document_id: DocumentId) -> DomainResult<()> {
        if self.status != DocumentRequestStatus::Requested
            && self.status != DocumentRequestStatus::Rejected
        {
            return Err(DomainError::conflict(
                "E_DOCUMENT_REQUEST_STATE",
                "only an open document request can receive a document",
            ));
        }
        self.document_id = Some(document_id);
        self.status = DocumentRequestStatus::Uploaded;
        Ok(())
    }

    pub fn verify(&mut self, by: impl Into<String>) -> DomainResult<()> {
        if self.status != DocumentRequestStatus::Uploaded {
            return Err(DomainError::conflict(
                "E_DOCUMENT_REQUEST_STATE",
                "only an uploaded document can be verified",
            ));
        }
        self.status = DocumentRequestStatus::Verified;
        self.note = Some(format!("verified by {}", by.into()));
        Ok(())
    }

    pub fn reject(&mut self, reason: &str) -> DomainResult<()> {
        if self.status != DocumentRequestStatus::Uploaded {
            return Err(DomainError::conflict(
                "E_DOCUMENT_REQUEST_STATE",
                "only an uploaded document can be rejected",
            ));
        }
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_DOCUMENT_REJECT_REASON",
                "rejecting a document needs a reason",
            ));
        }
        self.status = DocumentRequestStatus::Rejected;
        self.note = Some(reason.trim().to_owned());
        Ok(())
    }

    pub fn is_overdue(&self, today: BusinessDate) -> bool {
        matches!(
            self.status,
            DocumentRequestStatus::Requested | DocumentRequestStatus::Uploaded
        ) && self.due_on.is_some_and(|due| due < today)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    #[test]
    fn request_attach_verify() {
        let mut request = DocumentRequest::new(
            EmployeeId::new(),
            "KTP",
            Some(BusinessDate::parse("2026-11-10").unwrap()),
            now(),
        )
        .unwrap();
        assert_eq!(request.status, DocumentRequestStatus::Requested);
        request.attach(DocumentId::new()).unwrap();
        request.verify("Rina").unwrap();
        assert_eq!(request.status, DocumentRequestStatus::Verified);
    }

    #[test]
    fn rejection_needs_reason_and_can_be_reuploaded() {
        let mut request = DocumentRequest::new(EmployeeId::new(), "NPWP", None, now()).unwrap();
        request.attach(DocumentId::new()).unwrap();
        assert!(request.reject("no").is_err());
        request.reject("document is blurry").unwrap();
        request.attach(DocumentId::new()).unwrap();
        assert_eq!(request.status, DocumentRequestStatus::Uploaded);
    }

    #[test]
    fn overdue_only_while_open() {
        let request = DocumentRequest::new(
            EmployeeId::new(),
            "KTP",
            Some(BusinessDate::parse("2026-11-01").unwrap()),
            now(),
        )
        .unwrap();
        assert!(request.is_overdue(BusinessDate::parse("2026-11-02").unwrap()));
    }
}
