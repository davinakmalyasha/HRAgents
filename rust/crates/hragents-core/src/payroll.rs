use crate::error::{DomainError, DomainResult};
use crate::ids::{EmployeeId, OperatorId, PayrollRunId, RateTableId};
use crate::money::Money;
use crate::people::Employee;
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, schemars::JsonSchema,
)]
#[serde(rename_all = "snake_case")]
pub enum RateTableKind {
    BpjsKesehatan,
    BpjsKetenagakerjaanJht,
    BpjsKetenagakerjaanJp,
    BpjsJkk,
    BpjsJkm,
    Pph21Ter,
    Pph21Ptkp,
    OvertimePremium,
    ThrFormula,
    MinimumWage,
}

impl RateTableKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::BpjsKesehatan => "bpjs_kesehatan",
            Self::BpjsKetenagakerjaanJht => "bpjs_ketenagakerjaan_jht",
            Self::BpjsKetenagakerjaanJp => "bpjs_ketenagakerjaan_jp",
            Self::BpjsJkk => "bpjs_jkk",
            Self::BpjsJkm => "bpjs_jkm",
            Self::Pph21Ter => "pph21_ter",
            Self::Pph21Ptkp => "pph21_ptkp",
            Self::OvertimePremium => "overtime_premium",
            Self::ThrFormula => "thr_formula",
            Self::MinimumWage => "minimum_wage",
        }
    }

    /// Statutory tables that every monthly run must have, verified, before it
    /// can compute. A missing table blocks; there is no fallback constant.
    pub const REQUIRED_MONTHLY: [Self; 7] = [
        Self::BpjsKesehatan,
        Self::BpjsKetenagakerjaanJht,
        Self::BpjsKetenagakerjaanJp,
        Self::BpjsJkk,
        Self::BpjsJkm,
        Self::Pph21Ter,
        Self::Pph21Ptkp,
    ];
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct RateEntry {
    pub key: Option<String>,
    pub employee_share_bp: i64,
    pub employer_share_bp: i64,
    pub wage_cap: Option<Money>,
    pub flat_amount: Option<Money>,
    pub multiplier_bp: Option<i64>,
    pub lower_bound: Option<Money>,
    pub upper_bound: Option<Money>,
    pub hours_per_month: Option<i64>,
    pub note: Option<String>,
}

impl RateEntry {
    pub fn flat(key: Option<&str>, amount: Money) -> Self {
        Self {
            key: key.map(str::to_owned),
            employee_share_bp: 0,
            employer_share_bp: 0,
            wage_cap: None,
            flat_amount: Some(amount),
            multiplier_bp: None,
            lower_bound: None,
            upper_bound: None,
            hours_per_month: None,
            note: None,
        }
    }

    pub fn shares(key: Option<&str>, employee_bp: i64, employer_bp: i64) -> Self {
        Self {
            key: key.map(str::to_owned),
            employee_share_bp: employee_bp,
            employer_share_bp: employer_bp,
            wage_cap: None,
            flat_amount: None,
            multiplier_bp: None,
            lower_bound: None,
            upper_bound: None,
            hours_per_month: None,
            note: None,
        }
    }

    pub fn validate(&self) -> DomainResult<()> {
        for share in [self.employee_share_bp, self.employer_share_bp] {
            if !(0..=10_000).contains(&share) {
                return Err(DomainError::validation(
                    "E_RATE_SHARE",
                    "a contribution share is a basis-point value between 0 and 10000",
                ));
            }
        }
        if let Some(cap) = self.wage_cap
            && cap.is_negative()
        {
            return Err(DomainError::validation(
                "E_RATE_CAP",
                "a wage cap cannot be negative",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct RateTable {
    pub id: RateTableId,
    pub kind: RateTableKind,
    pub effective_from: BusinessDate,
    pub effective_to: Option<BusinessDate>,
    pub verified: bool,
    pub verified_by: Option<String>,
    pub verified_at: Option<UtcInstant>,
    pub source_note: Option<String>,
    pub entries: Vec<RateEntry>,
}

impl RateTable {
    pub fn is_effective_on(&self, date: BusinessDate) -> bool {
        self.effective_from <= date && self.effective_to.is_none_or(|end| date <= end)
    }

    pub fn is_usable(&self, date: BusinessDate) -> bool {
        self.verified && self.is_effective_on(date) && !self.entries.is_empty()
    }

    pub fn verify(
        &mut self,
        by: impl Into<String>,
        source_note: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if source_note.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_RATE_SOURCE",
                "verifying a statutory table requires a source note",
            ));
        }
        for entry in &self.entries {
            entry.validate()?;
        }
        self.verified = true;
        self.verified_by = Some(by.into());
        self.verified_at = Some(now);
        self.source_note = Some(source_note.trim().to_owned());
        Ok(())
    }

    pub fn entry(&self, key: Option<&str>) -> Option<&RateEntry> {
        match key {
            Some(key) => self
                .entries
                .iter()
                .find(|entry| entry.key.as_deref() == Some(key)),
            None => self.entries.first(),
        }
    }

    pub fn is_keyed(&self) -> bool {
        self.entries.iter().any(|entry| entry.key.is_some())
    }
}

#[derive(Debug, Clone, Default)]
pub struct RateTableSet {
    tables: BTreeMap<RateTableKind, RateTable>,
}

impl RateTableSet {
    pub fn insert(&mut self, table: RateTable) {
        self.tables.insert(table.kind, table);
    }

    pub fn get(&self, kind: RateTableKind) -> Option<&RateTable> {
        self.tables.get(&kind)
    }

    /// Every required table must be present, verified, effective, and non-empty.
    pub fn require_monthly(&self, on: BusinessDate) -> DomainResult<()> {
        let mut missing = Vec::new();
        for kind in RateTableKind::REQUIRED_MONTHLY {
            match self.tables.get(&kind) {
                Some(table) if table.is_usable(on) => {}
                Some(table) if !table.verified => {
                    missing.push(format!("{} (unverified)", kind.as_str()))
                }
                Some(_) => missing.push(format!("{} (not effective on {on})", kind.as_str())),
                None => missing.push(kind.as_str().to_owned()),
            }
        }
        if missing.is_empty() {
            Ok(())
        } else {
            Err(DomainError::RateTableUnverified {
                message: format!(
                    "payroll cannot compute without verified statutory tables: {}",
                    missing.join(", ")
                ),
            })
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum PayrollKind {
    Monthly,
    Thr,
    Final,
    Adjustment,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    Draft,
    Computed,
    Approved,
    Cancelled,
    Superseded,
}

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, schemars::JsonSchema,
)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Info,
    Warning,
    Error,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct PayrollAnomaly {
    pub code: String,
    pub severity: Severity,
    pub employee_id: Option<EmployeeId>,
    pub detail: String,
}

impl PayrollAnomaly {
    pub fn error(
        code: impl Into<String>,
        employee_id: Option<EmployeeId>,
        detail: impl Into<String>,
    ) -> Self {
        Self {
            code: code.into(),
            severity: Severity::Error,
            employee_id,
            detail: detail.into(),
        }
    }

    pub fn warning(
        code: impl Into<String>,
        employee_id: Option<EmployeeId>,
        detail: impl Into<String>,
    ) -> Self {
        Self {
            code: code.into(),
            severity: Severity::Warning,
            employee_id,
            detail: detail.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct PayrollInput {
    pub employee_id: EmployeeId,
    pub employee_name: String,
    pub base_salary: Money,
    pub fixed_allowances: Money,
    pub variable_allowances: Money,
    pub overtime_minutes: i64,
    pub absence_days: u32,
    pub working_days: u32,
    pub bonus: Money,
    pub other_deductions: Money,
    pub loan_deduction: Money,
    pub service_months: u32,
    pub severance_pay: Money,
    pub unused_leave_days_x2: i32,
    pub leave_payout_per_day: Money,
    pub note: Option<String>,
}

impl PayrollInput {
    pub fn new(
        employee_id: EmployeeId,
        employee_name: impl Into<String>,
        base_salary: Money,
    ) -> Self {
        Self {
            employee_id,
            employee_name: employee_name.into(),
            base_salary,
            fixed_allowances: Money::ZERO,
            variable_allowances: Money::ZERO,
            overtime_minutes: 0,
            absence_days: 0,
            working_days: 22,
            bonus: Money::ZERO,
            other_deductions: Money::ZERO,
            loan_deduction: Money::ZERO,
            service_months: 0,
            severance_pay: Money::ZERO,
            unused_leave_days_x2: 0,
            leave_payout_per_day: Money::ZERO,
            note: None,
        }
    }

    pub fn validate(&self) -> DomainResult<()> {
        if self.working_days == 0 {
            return Err(DomainError::validation(
                "E_WORKING_DAYS",
                "the period must have at least one working day",
            ));
        }
        if self.absence_days > self.working_days {
            return Err(DomainError::validation(
                "E_ABSENCE_DAYS",
                "absence days cannot exceed the working days in the period",
            ));
        }
        for (name, amount) in [
            ("base salary", self.base_salary),
            ("fixed allowances", self.fixed_allowances),
            ("variable allowances", self.variable_allowances),
            ("bonus", self.bonus),
            ("other deductions", self.other_deductions),
            ("loan deduction", self.loan_deduction),
            ("severance", self.severance_pay),
            ("leave payout", self.leave_payout_per_day),
        ] {
            if amount.is_negative() {
                return Err(DomainError::validation(
                    "E_NEGATIVE_INPUT",
                    format!("{name} cannot be negative"),
                ));
            }
        }
        if self.overtime_minutes < 0 {
            return Err(DomainError::validation(
                "E_OVERTIME",
                "overtime minutes cannot be negative",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct PayrollLine {
    pub employee_id: EmployeeId,
    pub employee_name: String,
    pub base_salary: Money,
    pub allowances: Money,
    pub overtime_pay: Money,
    pub bonus: Money,
    pub gross: Money,
    pub bpjs_kesehatan_employee: Money,
    pub bpjs_jht_employee: Money,
    pub bpjs_jp_employee: Money,
    pub pph21: Money,
    pub other_deductions: Money,
    pub total_deductions: Money,
    pub net: Money,
    pub bpjs_kesehatan_employer: Money,
    pub bpjs_jht_employer: Money,
    pub bpjs_jp_employer: Money,
    pub bpjs_jkk_employer: Money,
    pub bpjs_jkm_employer: Money,
    pub employer_cost: Money,
    pub thr_months_bp: Option<i64>,
    pub severance_pay: Money,
    pub leave_payout: Money,
    pub notes: Vec<String>,
}

impl PayrollLine {
    /// Fails if the line cannot be reconciled by hand. This is the last line of
    /// defence before a number reaches a bank file or a payslip.
    pub fn check_invariants(&self) -> DomainResult<()> {
        let earnings = Money::sum([
            self.base_salary,
            self.allowances,
            self.overtime_pay,
            self.bonus,
            self.severance_pay,
            self.leave_payout,
        ])?;
        if earnings != self.gross {
            return Err(DomainError::invariant(format!(
                "gross {} does not equal the sum of earnings {}",
                self.gross, earnings
            )));
        }
        let deductions = Money::sum([
            self.bpjs_kesehatan_employee,
            self.bpjs_jht_employee,
            self.bpjs_jp_employee,
            self.pph21,
            self.other_deductions,
        ])?;
        if deductions != self.total_deductions {
            return Err(DomainError::invariant(format!(
                "total deductions {} do not equal the sum of components {}",
                self.total_deductions, deductions
            )));
        }
        if self.gross.checked_sub(self.total_deductions)? != self.net {
            return Err(DomainError::invariant(
                "net pay does not equal gross minus deductions",
            ));
        }
        if self.net.is_negative() {
            return Err(DomainError::invariant("net pay is negative"));
        }
        let employer = Money::sum([
            self.bpjs_kesehatan_employer,
            self.bpjs_jht_employer,
            self.bpjs_jp_employer,
            self.bpjs_jkk_employer,
            self.bpjs_jkm_employer,
        ])?;
        if employer != self.employer_cost {
            return Err(DomainError::invariant(
                "employer cost does not equal the sum of employer shares",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct PayrollTotals {
    pub employees: usize,
    pub gross: Money,
    pub net: Money,
    pub employee_deductions: Money,
    pub employer_cost: Money,
    pub pph21: Money,
}

impl PayrollTotals {
    pub fn from_lines(lines: &[PayrollLine]) -> DomainResult<Self> {
        Ok(Self {
            employees: lines.len(),
            gross: Money::sum(lines.iter().map(|line| line.gross))?,
            net: Money::sum(lines.iter().map(|line| line.net))?,
            employee_deductions: Money::sum(lines.iter().map(|line| line.total_deductions))?,
            employer_cost: Money::sum(lines.iter().map(|line| line.employer_cost))?,
            pph21: Money::sum(lines.iter().map(|line| line.pph21))?,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct PayrollRun {
    pub id: PayrollRunId,
    pub kind: PayrollKind,
    pub period: BusinessDate,
    pub status: RunStatus,
    pub lines: Vec<PayrollLine>,
    pub anomalies: Vec<PayrollAnomaly>,
    pub totals: PayrollTotals,
    pub rate_table_ids: Vec<RateTableId>,
    pub created_at: UtcInstant,
    pub computed_at: Option<UtcInstant>,
    pub approved_at: Option<UtcInstant>,
    pub approved_by: Option<OperatorId>,
    pub supersede_reason: Option<String>,
}

impl PayrollRun {
    pub fn new(kind: PayrollKind, period: BusinessDate, now: UtcInstant) -> Self {
        Self {
            id: PayrollRunId::new(),
            kind,
            period,
            status: RunStatus::Draft,
            lines: Vec::new(),
            anomalies: Vec::new(),
            totals: PayrollTotals::default(),
            rate_table_ids: Vec::new(),
            created_at: now,
            computed_at: None,
            approved_at: None,
            approved_by: None,
            supersede_reason: None,
        }
    }

    pub fn has_blocking_anomalies(&self) -> bool {
        self.anomalies
            .iter()
            .any(|anomaly| anomaly.severity == Severity::Error)
    }

    pub fn blocking_count(&self) -> usize {
        self.anomalies
            .iter()
            .filter(|anomaly| anomaly.severity == Severity::Error)
            .count()
    }

    /// Sign-off requires a computed run, no blocking anomaly, and a fresh
    /// re-authentication enforced by the command layer before this is called.
    pub fn approve(&mut self, operator_id: OperatorId, now: UtcInstant) -> DomainResult<()> {
        if self.status != RunStatus::Computed {
            return Err(DomainError::conflict(
                "E_RUN_NOT_COMPUTED",
                "only a computed run can be approved",
            ));
        }
        if self.has_blocking_anomalies() {
            return Err(DomainError::conflict(
                "E_RUN_BLOCKING_ANOMALIES",
                format!(
                    "{} blocking anomaly(ies) must be resolved before sign-off",
                    self.blocking_count()
                ),
            ));
        }
        self.status = RunStatus::Approved;
        self.approved_at = Some(now);
        self.approved_by = Some(operator_id);
        Ok(())
    }

    pub fn supersede(&mut self, reason: &str) -> DomainResult<()> {
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_SUPERSEDE_REASON",
                "superseding a payroll run needs a reason",
            ));
        }
        if self.status == RunStatus::Superseded {
            return Err(DomainError::conflict(
                "E_ALREADY_SUPERSEDED",
                "this run has already been superseded",
            ));
        }
        self.status = RunStatus::Superseded;
        self.supersede_reason = Some(reason.trim().to_owned());
        Ok(())
    }
}

fn usable_on(table: Option<&RateTable>, on: BusinessDate) -> Option<&RateTable> {
    table.filter(|table| table.is_usable(on))
}

fn share(entry: Option<&RateEntry>, employer: bool, wage: Money) -> DomainResult<Money> {
    let Some(entry) = entry else {
        return Ok(Money::ZERO);
    };
    let bp = if employer {
        entry.employer_share_bp
    } else {
        entry.employee_share_bp
    };
    let effective = match entry.wage_cap {
        Some(cap) if wage > cap => cap,
        _ => wage,
    };
    effective.percent_bp(bp).map_err(Into::into)
}

fn ptkp_exemption(employee: Option<&Employee>, table: &RateTable) -> Money {
    let personal = table
        .entry(Some("personal"))
        .and_then(|entry| entry.flat_amount);
    let Some(personal) = personal else {
        return Money::ZERO;
    };
    let dependents = employee.map(|employee| employee.dependents).unwrap_or(0);
    let dependent = table
        .entry(Some("dependent"))
        .and_then(|entry| entry.flat_amount)
        .unwrap_or(Money::ZERO);
    personal
        .checked_add(
            dependent
                .checked_mul_int(i64::from(dependents))
                .unwrap_or(Money::ZERO),
        )
        .unwrap_or(personal)
}

pub fn compute_pph21(table: &RateTable, gross: Money, exemption: Money) -> DomainResult<Money> {
    let taxable = gross.checked_sub(exemption)?;
    if !taxable.is_negative() && taxable.is_zero() {
        return Ok(Money::ZERO);
    }
    if taxable.is_negative() {
        return Ok(Money::ZERO);
    }
    let mut brackets: Vec<&RateEntry> = table
        .entries
        .iter()
        .filter(|entry| entry.lower_bound.is_some())
        .collect();
    brackets.sort_by_key(|entry| entry.lower_bound.map(|value| value.sen()).unwrap_or(0));
    if brackets.is_empty() {
        return Ok(Money::ZERO);
    }
    let mut tax = Money::ZERO;
    for entry in &brackets {
        let lower = entry.lower_bound.unwrap_or(Money::ZERO);
        if taxable <= lower {
            break;
        }
        let slab_top = match entry.upper_bound {
            Some(upper) if upper < taxable => upper,
            _ => taxable,
        };
        if slab_top <= lower {
            continue;
        }
        let slab = slab_top.checked_sub(lower)?;
        if let Some(flat) = entry.flat_amount {
            tax = tax.checked_add(flat)?;
        } else {
            tax = tax.checked_add(slab.percent_bp(entry.employee_share_bp)?)?;
        }
        if entry.upper_bound.is_some_and(|upper| taxable <= upper) {
            break;
        }
    }
    if let Some(top) = brackets.last().and_then(|entry| entry.upper_bound)
        && taxable > top
    {
        return Err(DomainError::RateTableUnverified {
            message: format!(
                "PPh 21 TER brackets cover up to {top} but taxable income is {taxable}; extend and verify the table before paying this period"
            ),
        });
    }
    Ok(tax)
}

fn monthly_hours(table: &RateTable) -> Option<i64> {
    table
        .entry(Some("hours_per_month"))
        .and_then(|entry| entry.hours_per_month)
}

fn overtime_multipliers(table: &RateTable) -> Option<(i64, i64)> {
    let first = table
        .entry(Some("first_tier"))
        .and_then(|entry| entry.multiplier_bp)?;
    let rest = table
        .entry(Some("rest_tier"))
        .and_then(|entry| entry.multiplier_bp)?;
    Some((first, rest))
}

fn thr_months_bp(service_months: u32, table: &RateTable) -> Option<i64> {
    let key = if service_months < 12 {
        "under_1y".to_owned()
    } else {
        format!("{}y", service_months / 12)
    };
    let entry = table.entry(Some(&key)).or_else(|| {
        if service_months >= 96 {
            table.entry(Some("8y_plus"))
        } else {
            None
        }
    })?;
    entry.multiplier_bp
}

/// Compute one monthly line. This is the port of
/// `src/hr_agents/services/payroll.py::_compute_line`, with the known gaps fixed
/// rather than copied (see `FINAL` below).
pub fn compute_monthly_line(
    input: &PayrollInput,
    employee: Option<&Employee>,
    tables: &RateTableSet,
    on: BusinessDate,
) -> DomainResult<(PayrollLine, Vec<PayrollAnomaly>)> {
    input.validate()?;
    tables.require_monthly(on)?;
    let mut anomalies = Vec::new();

    let paid_fraction_num = i64::from(input.working_days - input.absence_days);
    let paid_fraction_den = i64::from(input.working_days);
    let wage = input.base_salary.checked_add(input.fixed_allowances)?;

    let base_paid = input
        .base_salary
        .mul_ratio(paid_fraction_num, paid_fraction_den)?;
    let fixed_paid = input
        .fixed_allowances
        .mul_ratio(paid_fraction_num, paid_fraction_den)?;
    let variable_paid = input
        .variable_allowances
        .mul_ratio(paid_fraction_num, paid_fraction_den)?;
    let contribution_wage = base_paid.checked_add(fixed_paid)?;

    let overtime_table = tables.get(RateTableKind::OvertimePremium);
    let overtime_pay = match overtime_table {
        Some(table) if table.is_usable(on) => {
            match (monthly_hours(table), overtime_multipliers(table)) {
                (Some(hours), Some((first_bp, rest_bp))) => {
                    let paid_num = i64::from(input.working_days) - i64::from(input.absence_days);
                    let days_worked = i64::max(
                        1,
                        (i64::from(input.working_days) * paid_num
                            + i64::from(input.working_days) / 2)
                            / i64::from(input.working_days),
                    );
                    let first_minutes = input.overtime_minutes.min(days_worked * 60);
                    let rest_minutes = input.overtime_minutes - first_minutes;
                    // Round once at the end, like the Python oracle. Quantising
                    // the hourly rate first shifts multi-hour lines by a few sen.
                    let weighted = first_bp * first_minutes + rest_bp * rest_minutes;
                    wage.mul_ratio(weighted, hours * 10_000 * 60)?
                }
                _ => {
                    anomalies.push(PayrollAnomaly::error(
                        "overtime_rules_missing",
                        Some(input.employee_id),
                        "the overtime_premium table has no complete hours_per_month, \
                         first_tier, and rest_tier rows, so overtime cannot be priced",
                    ));
                    Money::ZERO
                }
            }
        }
        _ => {
            if input.overtime_minutes > 0 {
                anomalies.push(PayrollAnomaly::error(
                    "overtime_rules_missing",
                    Some(input.employee_id),
                    "overtime was entered but no verified overtime_premium table is effective",
                ));
            }
            Money::ZERO
        }
    };

    if input.overtime_minutes > 60 * 4 {
        // 4 hours/day-equivalent over the period is worth a look, not a block.
        anomalies.push(PayrollAnomaly::warning(
            "overtime_excessive",
            Some(input.employee_id),
            format!(
                "{} overtime hours is unusual; verify with the manager",
                f64::from(i32::try_from(input.overtime_minutes / 60).unwrap_or(i32::MAX))
            ),
        ));
    }

    let gross = Money::sum([
        base_paid,
        fixed_paid,
        variable_paid,
        overtime_pay,
        input.bonus,
    ])?;

    if let Some(minimum_table) = tables
        .get(RateTableKind::MinimumWage)
        .filter(|table| table.is_usable(on))
        && let Some(minimum) = minimum_table
            .entry(None)
            .and_then(|entry| entry.flat_amount.or(entry.wage_cap))
        && contribution_wage < minimum
    {
        anomalies.push(PayrollAnomaly::error(
            "below_minimum_wage",
            Some(input.employee_id),
            format!(
                "paid wage {contribution_wage} is below the configured minimum                  {minimum}; paying it is a labour-law breach"
            ),
        ));
    }

    let kes = tables.get(RateTableKind::BpjsKesehatan);
    let jht = tables.get(RateTableKind::BpjsKetenagakerjaanJht);
    let jp = tables.get(RateTableKind::BpjsKetenagakerjaanJp);
    let jkk = tables.get(RateTableKind::BpjsJkk);
    let jkm = tables.get(RateTableKind::BpjsJkm);

    let kes_employee = share(
        usable_on(kes, on).and_then(|t| t.entry(None)),
        false,
        contribution_wage,
    )?;
    let kes_employer = share(
        usable_on(kes, on).and_then(|t| t.entry(None)),
        true,
        contribution_wage,
    )?;
    let jht_entry = usable_on(jht, on).and_then(|t| t.entry(Some("normal")));
    let jht_employee = share(jht_entry, false, contribution_wage)?;
    let jht_employer = share(jht_entry, true, contribution_wage)?;
    let jp_entry = usable_on(jp, on).and_then(|t| t.entry(None));
    let jp_employee = share(jp_entry, false, contribution_wage)?;
    let jp_employer = share(jp_entry, true, contribution_wage)?;
    let jkm_employer = share(
        usable_on(jkm, on).and_then(|t| t.entry(None)),
        true,
        contribution_wage,
    )?;

    let risk_key = employee
        .and_then(|employee| employee.jkk_risk_class)
        .map(|class| format!("class_{class}"));
    let mut jkk_employer = share(
        usable_on(jkk, on).and_then(|t| t.entry(risk_key.as_deref())),
        true,
        contribution_wage,
    )?;
    if usable_on(jkk, on).is_some_and(|table| table.is_keyed()) && risk_key.is_none() {
        anomalies.push(PayrollAnomaly::error(
            "jkk_risk_class_unrecorded",
            Some(input.employee_id),
            "the JKK table is keyed by risk class but this employee has none; record the \
             BPJS JKK risk class before paying",
        ));
        jkk_employer = Money::ZERO;
    }

    let pph_table = tables.get(RateTableKind::Pph21Ter);
    let pph21 = match pph_table {
        Some(table) if table.is_usable(on) => {
            let exemption = match tables.get(RateTableKind::Pph21Ptkp) {
                Some(ptkp) if ptkp.is_usable(on) => ptkp_exemption(employee, ptkp),
                _ => Money::ZERO,
            };
            let tax = compute_pph21(table, gross, exemption)?;
            if exemption.is_zero() {
                anomalies.push(PayrollAnomaly::error(
                    "pph21_ptkp_missing",
                    Some(input.employee_id),
                    format!(
                        "TER withheld {tax} with no personal exemption applied because the \
                         pph21_ptkp table has no usable 'personal' row"
                    ),
                ));
            }
            tax
        }
        _ => Money::ZERO,
    };

    let other = input.other_deductions.checked_add(input.loan_deduction)?;
    let total_deductions = Money::sum([kes_employee, jht_employee, jp_employee, pph21, other])?;
    let net = gross.checked_sub(total_deductions)?;
    if net.is_negative() {
        anomalies.push(PayrollAnomaly::error(
            "negative_net",
            Some(input.employee_id),
            format!("computed net pay is negative ({net}); correct the inputs"),
        ));
    }

    let employer_cost = Money::sum([
        kes_employer,
        jht_employer,
        jp_employer,
        jkk_employer,
        jkm_employer,
    ])?;

    let line = PayrollLine {
        employee_id: input.employee_id,
        employee_name: input.employee_name.clone(),
        base_salary: base_paid,
        allowances: fixed_paid.checked_add(variable_paid)?,
        overtime_pay,
        bonus: input.bonus,
        gross,
        bpjs_kesehatan_employee: kes_employee,
        bpjs_jht_employee: jht_employee,
        bpjs_jp_employee: jp_employee,
        pph21,
        other_deductions: other,
        total_deductions,
        net,
        bpjs_kesehatan_employer: kes_employer,
        bpjs_jht_employer: jht_employer,
        bpjs_jp_employer: jp_employer,
        bpjs_jkk_employer: jkk_employer,
        bpjs_jkm_employer: jkm_employer,
        employer_cost,
        thr_months_bp: None,
        severance_pay: Money::ZERO,
        leave_payout: Money::ZERO,
        notes: input.note.iter().cloned().collect(),
    };
    line.check_invariants()?;
    Ok((line, anomalies))
}

/// THR / termination entitlement. Unlike the Python source, a missing
/// entitlement ladder blocks instead of paying zero, and BPJS is explicitly
/// unmodelled rather than silently applying the monthly contribution rules.
pub fn compute_thr_line(
    input: &PayrollInput,
    _employee: Option<&Employee>,
    tables: &RateTableSet,
    on: BusinessDate,
) -> DomainResult<(PayrollLine, Vec<PayrollAnomaly>)> {
    input.validate()?;
    let table =
        tables
            .get(RateTableKind::ThrFormula)
            .ok_or_else(|| DomainError::RateTableUnverified {
                message: "no thr_formula table is configured; the entitlement cannot be guessed"
                    .to_owned(),
            })?;
    if !table.is_usable(on) {
        return Err(DomainError::RateTableUnverified {
            message: "the thr_formula table is unverified or not effective for this period"
                .to_owned(),
        });
    }
    let mut anomalies = vec![PayrollAnomaly::error(
        "thr_bpjs_unmodelled",
        Some(input.employee_id),
        "BPJS contributions are not computed on this termination payout. Which \
         contributions apply, and at what proration, depends on the employer's arrangement. \
         A named human must settle this before sign-off",
    )];
    let monthly_wage = input.base_salary.checked_add(input.fixed_allowances)?;
    let months_bp = thr_months_bp(input.service_months, table).ok_or_else(|| {
        DomainError::RateTableUnverified {
            message: format!(
                "no thr_formula row covers {} months of service; enter and verify the table",
                input.service_months
            ),
        }
    })?;
    let paid_fraction_num = i64::from(input.working_days - input.absence_days);
    let paid_fraction_den = i64::from(input.working_days);
    let entitlement = monthly_wage.mul_ratio(months_bp, 10_000)?;
    let thr_pay = entitlement.mul_ratio(paid_fraction_num, paid_fraction_den)?;
    let other = input.other_deductions.checked_add(input.loan_deduction)?;
    let net = thr_pay.checked_sub(other)?;
    if net.is_negative() {
        anomalies.push(PayrollAnomaly::error(
            "negative_net",
            Some(input.employee_id),
            "THR deductions exceed the entitlement",
        ));
    }
    let line = PayrollLine {
        employee_id: input.employee_id,
        employee_name: input.employee_name.clone(),
        base_salary: thr_pay,
        allowances: Money::ZERO,
        overtime_pay: Money::ZERO,
        bonus: Money::ZERO,
        gross: thr_pay,
        bpjs_kesehatan_employee: Money::ZERO,
        bpjs_jht_employee: Money::ZERO,
        bpjs_jp_employee: Money::ZERO,
        pph21: Money::ZERO,
        other_deductions: other,
        total_deductions: other,
        net,
        bpjs_kesehatan_employer: Money::ZERO,
        bpjs_jht_employer: Money::ZERO,
        bpjs_jp_employer: Money::ZERO,
        bpjs_jkk_employer: Money::ZERO,
        bpjs_jkm_employer: Money::ZERO,
        employer_cost: Money::ZERO,
        thr_months_bp: Some(months_bp),
        severance_pay: Money::ZERO,
        leave_payout: Money::ZERO,
        notes: input.note.iter().cloned().collect(),
    };
    line.check_invariants()?;
    Ok((line, anomalies))
}

/// Final settlement, fixed relative to Python.
///
/// Python routed `FINAL` through `_compute_line`, which pays a normal monthly
/// wage and silently omits severance and unused-leave payout. This function
/// computes the wage component with the normal monthly rules, then adds
/// severance and leave payout outside the BPJS base, and flags the tax review
/// that a final settlement always needs. It never guesses a statutory
/// severance multiplier.
pub fn compute_final_line(
    input: &PayrollInput,
    employee: Option<&Employee>,
    tables: &RateTableSet,
    on: BusinessDate,
) -> DomainResult<(PayrollLine, Vec<PayrollAnomaly>)> {
    let (mut line, mut anomalies) = compute_monthly_line(input, employee, tables, on)?;
    let leave_days = i64::from(input.unused_leave_days_x2);
    let leave_payout = input.leave_payout_per_day.mul_ratio(leave_days, 2)?;
    let severance = input.severance_pay;
    if severance.is_zero() && input.service_months >= 12 {
        anomalies.push(PayrollAnomaly::warning(
            "severance_not_entered",
            Some(input.employee_id),
            "no severance was entered for a final settlement; confirm this is intentional",
        ));
    }
    line.severance_pay = severance;
    line.leave_payout = leave_payout;
    line.gross = line
        .gross
        .checked_add(severance)?
        .checked_add(leave_payout)?;
    line.net = line.gross.checked_sub(line.total_deductions)?;
    line.check_invariants()?;
    anomalies.push(PayrollAnomaly::warning(
        "final_tax_review_required",
        Some(input.employee_id),
        "final-settlement tax treatment (severance and leave payout) must be reviewed by a \
         named human before the run is signed off",
    ));
    Ok((line, anomalies))
}

/// Compute a whole run. The caller supplies the effective rate tables and the
/// period's working days; the function is pure and deterministic.
pub fn compute_run(
    kind: PayrollKind,
    period: BusinessDate,
    inputs: &[PayrollInput],
    employees: &BTreeMap<EmployeeId, Employee>,
    tables: &RateTableSet,
    now: UtcInstant,
) -> DomainResult<PayrollRun> {
    let mut run = PayrollRun::new(kind, period, now);
    if inputs.is_empty() {
        return Err(DomainError::validation(
            "E_PAYROLL_EMPTY",
            "a payroll run needs at least one employee input",
        ));
    }
    let mut seen = std::collections::BTreeSet::new();
    for input in inputs {
        if !seen.insert(input.employee_id) {
            return Err(DomainError::validation(
                "E_PAYROLL_DUPLICATE",
                format!(
                    "employee {} appears twice in the same run",
                    input.employee_id
                ),
            ));
        }
        let employee = employees.get(&input.employee_id);
        let (line, mut anomalies) = match kind {
            PayrollKind::Monthly | PayrollKind::Adjustment => {
                compute_monthly_line(input, employee, tables, period)?
            }
            PayrollKind::Thr => compute_thr_line(input, employee, tables, period)?,
            PayrollKind::Final => compute_final_line(input, employee, tables, period)?,
        };
        run.lines.push(line);
        run.anomalies.append(&mut anomalies);
    }
    run.totals = PayrollTotals::from_lines(&run.lines)?;
    for kind in RateTableKind::REQUIRED_MONTHLY {
        if let Some(table) = tables.get(kind) {
            run.rate_table_ids.push(table.id);
        }
    }
    run.status = RunStatus::Computed;
    run.computed_at = Some(now);
    Ok(run)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ids::EmployeeId;

    fn day() -> BusinessDate {
        BusinessDate::parse("2026-11-01").unwrap()
    }

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    fn table(kind: RateTableKind, entries: Vec<RateEntry>) -> RateTable {
        RateTable {
            id: RateTableId::new(),
            kind,
            effective_from: BusinessDate::parse("2026-01-01").unwrap(),
            effective_to: None,
            verified: true,
            verified_by: Some("Rina".into()),
            verified_at: Some(now()),
            source_note: Some("operator-verified fixture".into()),
            entries,
        }
    }

    fn entries(kind: RateTableKind) -> Vec<RateEntry> {
        match kind {
            RateTableKind::BpjsKesehatan => vec![RateEntry::shares(None, 100, 400)],
            RateTableKind::BpjsKetenagakerjaanJht => {
                vec![RateEntry::shares(Some("normal"), 200, 370)]
            }
            RateTableKind::BpjsKetenagakerjaanJp => vec![RateEntry::shares(None, 100, 200)],
            RateTableKind::BpjsJkk => vec![RateEntry::shares(Some("class_1"), 0, 24)],
            RateTableKind::BpjsJkm => vec![RateEntry::shares(None, 0, 30)],
            RateTableKind::Pph21Ter => vec![
                RateEntry {
                    key: None,
                    employee_share_bp: 50,
                    employer_share_bp: 0,
                    wage_cap: None,
                    flat_amount: None,
                    multiplier_bp: None,
                    lower_bound: Some(Money::from_rupiah(0).unwrap()),
                    upper_bound: Some(Money::from_rupiah(10_000_000).unwrap()),
                    hours_per_month: None,
                    note: None,
                },
                RateEntry {
                    key: None,
                    employee_share_bp: 100,
                    employer_share_bp: 0,
                    wage_cap: None,
                    flat_amount: None,
                    multiplier_bp: None,
                    lower_bound: Some(Money::from_rupiah(10_000_000).unwrap()),
                    upper_bound: Some(Money::from_rupiah(100_000_000).unwrap()),
                    hours_per_month: None,
                    note: None,
                },
            ],
            RateTableKind::Pph21Ptkp => vec![
                RateEntry::flat(Some("personal"), Money::from_rupiah(54_000_000).unwrap()),
                RateEntry::flat(Some("dependent"), Money::from_rupiah(4_500_000).unwrap()),
            ],
            RateTableKind::OvertimePremium => vec![
                RateEntry {
                    key: Some("hours_per_month".into()),
                    employee_share_bp: 0,
                    employer_share_bp: 0,
                    wage_cap: None,
                    flat_amount: None,
                    multiplier_bp: None,
                    lower_bound: None,
                    upper_bound: None,
                    hours_per_month: Some(173),
                    note: None,
                },
                RateEntry {
                    key: Some("first_tier".into()),
                    employee_share_bp: 0,
                    employer_share_bp: 0,
                    wage_cap: None,
                    flat_amount: None,
                    multiplier_bp: Some(15_000),
                    lower_bound: None,
                    upper_bound: None,
                    hours_per_month: None,
                    note: None,
                },
                RateEntry {
                    key: Some("rest_tier".into()),
                    employee_share_bp: 0,
                    employer_share_bp: 0,
                    wage_cap: None,
                    flat_amount: None,
                    multiplier_bp: Some(20_000),
                    lower_bound: None,
                    upper_bound: None,
                    hours_per_month: None,
                    note: None,
                },
            ],
            RateTableKind::ThrFormula => vec![
                RateEntry {
                    key: Some("under_1y".into()),
                    employee_share_bp: 0,
                    employer_share_bp: 0,
                    wage_cap: None,
                    flat_amount: None,
                    multiplier_bp: Some(10_000),
                    lower_bound: None,
                    upper_bound: None,
                    hours_per_month: None,
                    note: None,
                },
                RateEntry {
                    key: Some("2y".into()),
                    employee_share_bp: 0,
                    employer_share_bp: 0,
                    wage_cap: None,
                    flat_amount: None,
                    multiplier_bp: Some(20_000),
                    lower_bound: None,
                    upper_bound: None,
                    hours_per_month: None,
                    note: None,
                },
            ],
            RateTableKind::MinimumWage => {
                vec![RateEntry::flat(
                    None,
                    Money::from_rupiah(5_000_000).unwrap(),
                )]
            }
        }
    }

    fn tables() -> RateTableSet {
        let mut set = RateTableSet::default();
        for kind in [
            RateTableKind::BpjsKesehatan,
            RateTableKind::BpjsKetenagakerjaanJht,
            RateTableKind::BpjsKetenagakerjaanJp,
            RateTableKind::BpjsJkk,
            RateTableKind::BpjsJkm,
            RateTableKind::Pph21Ter,
            RateTableKind::Pph21Ptkp,
            RateTableKind::OvertimePremium,
            RateTableKind::ThrFormula,
            RateTableKind::MinimumWage,
        ] {
            set.insert(table(kind, entries(kind)));
        }
        set
    }

    fn input() -> PayrollInput {
        let mut input = PayrollInput::new(
            EmployeeId::new(),
            "Ayu Lestari",
            Money::from_rupiah(10_000_000).unwrap(),
        );
        input.fixed_allowances = Money::from_rupiah(2_000_000).unwrap();
        input.working_days = 22;
        input.service_months = 30;
        input
    }

    fn employee(input: &PayrollInput) -> Employee {
        let mut employee = Employee::new(
            "E-001",
            "Ayu Lestari",
            "Engineer",
            "Product",
            BusinessDate::parse("2024-01-15").unwrap(),
            now(),
        );
        employee.id = input.employee_id;
        employee.dependents = 1;
        employee.jkk_risk_class = Some(1);
        employee
    }

    #[test]
    fn monthly_line_reconciles_to_the_sen() {
        let input = input();
        let employees = BTreeMap::from([(input.employee_id, employee(&input))]);
        let run = compute_run(
            PayrollKind::Monthly,
            day(),
            std::slice::from_ref(&input),
            &employees,
            &tables(),
            now(),
        )
        .unwrap();
        let line = &run.lines[0];
        line.check_invariants().unwrap();
        assert_eq!(line.gross, Money::from_rupiah(12_000_000).unwrap());
        // 1% + 2% + 1% employee BPJS = 480,000; PPh 21 0.5% of 12m less PTKP 58.5m = 0.
        assert_eq!(
            line.bpjs_kesehatan_employee,
            Money::from_rupiah(120_000).unwrap()
        );
        assert_eq!(line.total_deductions, Money::from_rupiah(480_000).unwrap());
        assert_eq!(line.net, Money::from_rupiah(11_520_000).unwrap());
        assert_eq!(line.employer_cost, Money::from_rupiah(1_228_800).unwrap());
        assert_eq!(run.totals.net, Money::from_rupiah(11_520_000).unwrap());
    }

    #[test]
    fn absence_prorates_wages_but_not_overtime() {
        let mut input = input();
        input.absence_days = 2;
        input.overtime_minutes = 120;
        let employees = BTreeMap::from([(input.employee_id, employee(&input))]);
        let run = compute_run(
            PayrollKind::Monthly,
            day(),
            std::slice::from_ref(&input),
            &employees,
            &tables(),
            now(),
        )
        .unwrap();
        let line = &run.lines[0];
        assert_eq!(line.base_salary, Money::from_sen(909_090_909));
        assert_eq!(line.allowances, Money::from_sen(181_818_182));
        assert!(line.overtime_pay > Money::ZERO);
        line.check_invariants().unwrap();
    }

    #[test]
    fn missing_verified_table_blocks_the_run() {
        let mut set = tables();
        set.tables.remove(&RateTableKind::BpjsJkk);
        let input = input();
        let employees = BTreeMap::from([(input.employee_id, employee(&input))]);
        assert!(matches!(
            compute_run(
                PayrollKind::Monthly,
                day(),
                std::slice::from_ref(&input),
                &employees,
                &set,
                now()
            ),
            Err(DomainError::RateTableUnverified { .. })
        ));
    }

    #[test]
    fn pph21_is_progressive_not_flat() {
        let table = table(RateTableKind::Pph21Ter, entries(RateTableKind::Pph21Ter));
        let tax =
            compute_pph21(&table, Money::from_rupiah(20_000_000).unwrap(), Money::ZERO).unwrap();
        // 0.5% of 10m + 1% of 10m = 150,000; a flat first-bracket bug would give 200,000.
        assert_eq!(tax, Money::from_rupiah(150_000).unwrap());
    }

    #[test]
    fn thr_uses_the_service_ladder_and_blocks_bpjs() {
        let input = input();
        let employees = BTreeMap::from([(input.employee_id, employee(&input))]);
        let run = compute_run(
            PayrollKind::Thr,
            day(),
            std::slice::from_ref(&input),
            &employees,
            &tables(),
            now(),
        )
        .unwrap();
        let line = &run.lines[0];
        assert_eq!(line.thr_months_bp, Some(20_000));
        assert_eq!(line.gross, Money::from_rupiah(24_000_000).unwrap());
        assert!(run.has_blocking_anomalies());
        assert!(
            run.anomalies
                .iter()
                .any(|a| a.code == "thr_bpjs_unmodelled")
        );
    }

    #[test]
    fn final_settlement_includes_severance_and_leave() {
        let mut input = input();
        input.severance_pay = Money::from_rupiah(5_000_000).unwrap();
        input.unused_leave_days_x2 = 5;
        input.leave_payout_per_day = Money::from_rupiah(500_000).unwrap();
        let employees = BTreeMap::from([(input.employee_id, employee(&input))]);
        let run = compute_run(
            PayrollKind::Final,
            day(),
            std::slice::from_ref(&input),
            &employees,
            &tables(),
            now(),
        )
        .unwrap();
        let line = &run.lines[0];
        assert_eq!(line.severance_pay, Money::from_rupiah(5_000_000).unwrap());
        assert_eq!(line.leave_payout, Money::from_rupiah(1_250_000).unwrap());
        line.check_invariants().unwrap();
        assert!(
            run.anomalies
                .iter()
                .any(|a| a.code == "final_tax_review_required")
        );
    }

    #[test]
    fn sign_off_refuses_blocking_anomalies() {
        let mut run = PayrollRun::new(PayrollKind::Monthly, day(), now());
        run.status = RunStatus::Computed;
        run.anomalies
            .push(PayrollAnomaly::error("x", None, "something is wrong"));
        assert!(run.approve(OperatorId::new(), now()).is_err());
        run.anomalies.clear();
        run.approve(OperatorId::new(), now()).unwrap();
        assert_eq!(run.status, RunStatus::Approved);
    }
}
