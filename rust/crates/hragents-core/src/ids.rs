use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;
use uuid::Uuid;

macro_rules! id_type {
    ($name:ident, $prefix:literal) => {
        #[derive(
            Debug,
            Clone,
            Copy,
            PartialEq,
            Eq,
            PartialOrd,
            Ord,
            Hash,
            Serialize,
            Deserialize,
            schemars::JsonSchema,
        )]
        #[serde(transparent)]
        pub struct $name(Uuid);

        impl $name {
            pub fn new() -> Self {
                Self(Uuid::new_v4())
            }

            pub const fn from_uuid(value: Uuid) -> Self {
                Self(value)
            }

            pub const fn as_uuid(self) -> Uuid {
                self.0
            }

            /// Human-facing short reference, e.g. `#E-3F2A9C`. UUIDs never appear
            /// in a label, a URL, or a toast.
            pub fn short_ref(self) -> String {
                let hex = self.0.simple().to_string();
                format!("#{}-{}", $prefix, hex[..6].to_uppercase())
            }
        }

        impl Default for $name {
            fn default() -> Self {
                Self::new()
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                write!(f, "{}", self.0)
            }
        }

        impl FromStr for $name {
            type Err = uuid::Error;

            fn from_str(s: &str) -> Result<Self, Self::Err> {
                Ok(Self(Uuid::parse_str(s)?))
            }
        }
    };
}

id_type!(CompanyId, "C");
id_type!(OperatorId, "O");
id_type!(EmployeeId, "E");
id_type!(CandidateId, "A");
id_type!(ApplicationId, "AP");
id_type!(JobId, "J");
id_type!(DocumentId, "D");
id_type!(AuditId, "AU");
id_type!(OnboardingPlanId, "ON");
id_type!(LeaveRequestId, "L");
id_type!(LeaveTypeId, "LT");
id_type!(PayrollRunId, "R");
id_type!(EvaluationId, "EV");
id_type!(ConsentId, "CO");
id_type!(ErasureRequestId, "ER");
id_type!(ContractId, "CT");
id_type!(RateTableId, "RT");
id_type!(SessionId, "S");
id_type!(ReviewCycleId, "RC");
id_type!(ReviewAssignmentId, "RA");
id_type!(GoalId, "G");
id_type!(OffboardingPlanId, "OFF");
id_type!(DocumentRequestId, "DR");
