use crate::ids::EmployeeId;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct HeadcountRow {
    pub org_unit: String,
    pub active: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct PayrollCostRow {
    pub year: i32,
    pub month: u32,
    pub employees: u32,
    pub net_sen: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct LeaveRecapRow {
    pub employee_id: EmployeeId,
    pub employee_no: String,
    pub full_name: String,
    pub approved: u32,
    pub pending: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct HiringFunnelRow {
    pub job_id: String,
    pub title: String,
    pub applied: u32,
    pub interviewed: u32,
    pub offered: u32,
    pub hired: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct CompanyReport {
    pub headcount: Vec<HeadcountRow>,
    pub total_active: u32,
    pub payroll_cost: Vec<PayrollCostRow>,
    pub leave_recap: Vec<LeaveRecapRow>,
    pub hiring_funnel: Vec<HiringFunnelRow>,
}

/// Pure aggregation. Inputs are already-filtered rows from the store; this
/// module never touches a database or the network.
pub fn headcount_by_org(units: Vec<(String, u32)>) -> Vec<HeadcountRow> {
    let mut map: BTreeMap<String, u32> = BTreeMap::new();
    for (unit, count) in units {
        let name = unit.trim();
        if name.is_empty() {
            continue;
        }
        *map.entry(name.to_owned()).or_default() += count;
    }
    map.into_iter()
        .map(|(org_unit, active)| HeadcountRow { org_unit, active })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn headcount_merges_units_and_skips_blank() {
        let rows = headcount_by_org(vec![
            ("Engineering".into(), 2),
            ("Engineering".into(), 1),
            ("  ".into(), 9),
            ("HR".into(), 1),
        ]);
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].org_unit, "Engineering");
        assert_eq!(rows[0].active, 3);
    }
}
