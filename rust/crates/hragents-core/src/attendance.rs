use crate::error::{DomainError, DomainResult};
use crate::ids::{CheckinId, EmployeeId, ShiftId};
use crate::time::{BusinessDate, UtcInstant};
use chrono::{Datelike, Weekday};
use serde::{Deserialize, Serialize};

/// Minutes since midnight, 0..=1440.
pub type DayMinutes = i64;

/// Workdays mask: bit 0 = Monday .. bit 6 = Sunday.
pub const MON_FRI_MASK: u8 = 0b0001_1111;
pub const ALL_DAYS_MASK: u8 = 0b0111_1111;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Shift {
    pub id: ShiftId,
    pub name: String,
    pub start_minute: DayMinutes,
    pub end_minute: DayMinutes,
    pub grace_minutes: DayMinutes,
    pub workdays_mask: u8,
    pub created_at: UtcInstant,
}

impl Shift {
    pub fn new(
        name: impl Into<String>,
        start_minute: DayMinutes,
        end_minute: DayMinutes,
        grace_minutes: DayMinutes,
        workdays_mask: u8,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        let name = name.into();
        if name.trim().len() < 2 {
            return Err(DomainError::validation(
                "E_SHIFT_NAME",
                "a shift needs a name of at least 2 characters",
            ));
        }
        for (label, value) in [("start", start_minute), ("end", end_minute)] {
            if !(0..=1_440).contains(&value) {
                return Err(DomainError::validation(
                    "E_SHIFT_TIME",
                    format!("shift {label} must be 0..=1440 minutes"),
                ));
            }
        }
        if end_minute <= start_minute {
            return Err(DomainError::validation(
                "E_SHIFT_TIME",
                "shift end must be after shift start (no overnight shifts in this edition)",
            ));
        }
        if !(0..=120).contains(&grace_minutes) {
            return Err(DomainError::validation(
                "E_SHIFT_GRACE",
                "grace must be 0..=120 minutes",
            ));
        }
        if workdays_mask == 0 || workdays_mask > ALL_DAYS_MASK {
            return Err(DomainError::validation(
                "E_SHIFT_DAYS",
                "a shift needs at least one workday",
            ));
        }
        Ok(Self {
            id: ShiftId::new(),
            name: name.trim().to_owned(),
            start_minute,
            end_minute,
            grace_minutes,
            workdays_mask,
            created_at: now,
        })
    }

    pub fn is_workday(&self, date: BusinessDate) -> bool {
        let weekday = date.naive().weekday();
        let bit = match weekday {
            Weekday::Mon => 0,
            Weekday::Tue => 1,
            Weekday::Wed => 2,
            Weekday::Thu => 3,
            Weekday::Fri => 4,
            Weekday::Sat => 5,
            Weekday::Sun => 6,
        };
        (self.workdays_mask >> bit) & 1 == 1
    }

    pub fn late_minutes(&self, in_minute: DayMinutes) -> DayMinutes {
        (in_minute - (self.start_minute + self.grace_minutes)).max(0)
    }

    pub fn overtime_minutes(&self, out_minute: DayMinutes) -> DayMinutes {
        (out_minute - (self.end_minute + self.grace_minutes)).max(0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum CheckinSource {
    Manual,
    Import,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Checkin {
    pub id: CheckinId,
    pub employee_id: EmployeeId,
    pub date: BusinessDate,
    pub in_minute: DayMinutes,
    pub out_minute: DayMinutes,
    pub source: CheckinSource,
    pub note: Option<String>,
    pub created_at: UtcInstant,
}

impl Checkin {
    pub fn record(
        employee_id: EmployeeId,
        date: BusinessDate,
        in_minute: DayMinutes,
        out_minute: DayMinutes,
        source: CheckinSource,
        note: Option<String>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        for (label, value) in [("in", in_minute), ("out", out_minute)] {
            if !(0..=1_440).contains(&value) {
                return Err(DomainError::validation(
                    "E_CHECKIN_TIME",
                    format!("check-in {label} must be 0..=1440 minutes"),
                ));
            }
        }
        if out_minute <= in_minute {
            return Err(DomainError::validation(
                "E_CHECKIN_TIME",
                "check-out must be after check-in on the same day",
            ));
        }
        if let Some(note) = note.as_deref()
            && note.len() > 500
        {
            return Err(DomainError::validation(
                "E_CHECKIN_NOTE",
                "a check-in note is at most 500 characters",
            ));
        }
        Ok(Self {
            id: CheckinId::new(),
            employee_id,
            date,
            in_minute,
            out_minute,
            source,
            note,
            created_at: now,
        })
    }

    pub fn worked_minutes(&self) -> DayMinutes {
        self.out_minute - self.in_minute
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct AttendanceDay {
    pub date: BusinessDate,
    pub present: bool,
    pub late_minutes: DayMinutes,
    pub overtime_minutes: DayMinutes,
    pub worked_minutes: DayMinutes,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct AttendanceSummary {
    pub employee_id: EmployeeId,
    pub year: i32,
    pub month: u32,
    pub workdays: u32,
    pub present_days: u32,
    pub absent_days: u32,
    pub late_minutes: DayMinutes,
    pub overtime_minutes: DayMinutes,
    pub worked_minutes: DayMinutes,
}

/// Deterministic monthly summary. `checkins` may contain duplicates for one
/// date; the earliest in and latest out win. Dates outside the month are
/// ignored. Absent days are workdays without a check-in; leave and holidays
/// are subtracted by the caller, which owns that data.
pub fn summarize_month(
    employee_id: EmployeeId,
    year: i32,
    month: u32,
    shift: &Shift,
    checkins: &[Checkin],
    workdays_in_month: u32,
) -> AttendanceSummary {
    use std::collections::BTreeMap;
    let mut per_day: BTreeMap<BusinessDate, (DayMinutes, DayMinutes)> = BTreeMap::new();
    for checkin in checkins {
        if checkin.employee_id != employee_id {
            continue;
        }
        if checkin.date.year() != year || checkin.date.month() != month {
            continue;
        }
        per_day
            .entry(checkin.date)
            .and_modify(|slot| {
                slot.0 = slot.0.min(checkin.in_minute);
                slot.1 = slot.1.max(checkin.out_minute);
            })
            .or_insert((checkin.in_minute, checkin.out_minute));
    }
    let mut present_days = 0_u32;
    let mut late_minutes = 0_i64;
    let mut overtime_minutes = 0_i64;
    let mut worked_minutes = 0_i64;
    for (in_min, out_min) in per_day.values() {
        present_days += 1;
        late_minutes += shift.late_minutes(*in_min);
        overtime_minutes += shift.overtime_minutes(*out_min);
        worked_minutes += out_min - in_min;
    }
    let absent_days = workdays_in_month.saturating_sub(present_days);
    AttendanceSummary {
        employee_id,
        year,
        month,
        workdays: workdays_in_month,
        present_days,
        absent_days,
        late_minutes,
        overtime_minutes,
        worked_minutes,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::time::UtcInstant;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_700_000_000_000).unwrap()
    }

    #[test]
    fn shift_rejects_bad_times() {
        assert!(Shift::new("Pagi", 480, 480, 10, MON_FRI_MASK, now()).is_err());
        assert!(Shift::new("Pagi", 1020, 480, 10, MON_FRI_MASK, now()).is_err());
        assert!(Shift::new("P", 480, 1020, 10, MON_FRI_MASK, now()).is_err());
        assert!(Shift::new("Pagi", 480, 1020, 200, MON_FRI_MASK, now()).is_err());
        assert!(Shift::new("Pagi", 480, 1020, 10, 0, now()).is_err());
    }

    #[test]
    fn checkin_rejects_out_before_in() {
        let emp = EmployeeId::new();
        let date = BusinessDate::parse("2026-02-02").unwrap();
        assert!(
            Checkin::record(emp, date, 1_020, 480, CheckinSource::Manual, None, now()).is_err()
        );
        assert!(Checkin::record(emp, date, -1, 480, CheckinSource::Manual, None, now()).is_err());
    }

    #[test]
    fn late_and_overtime_use_grace() {
        let shift = Shift::new("Pagi", 480, 1_020, 10, MON_FRI_MASK, now()).unwrap();
        assert_eq!(shift.late_minutes(485), 0);
        assert_eq!(shift.late_minutes(500), 10);
        assert_eq!(shift.overtime_minutes(1_025), 0);
        assert_eq!(shift.overtime_minutes(1_060), 30);
    }

    #[test]
    fn summary_counts_present_and_absent() {
        let emp = EmployeeId::new();
        let shift = Shift::new("Pagi", 480, 1_020, 10, MON_FRI_MASK, now()).unwrap();
        let d1 = BusinessDate::parse("2026-02-02").unwrap();
        let d2 = BusinessDate::parse("2026-02-03").unwrap();
        let c1 = Checkin::record(emp, d1, 485, 1_060, CheckinSource::Manual, None, now()).unwrap();
        let c2 = Checkin::record(emp, d2, 480, 1_020, CheckinSource::Manual, None, now()).unwrap();
        let summary = summarize_month(emp, 2026, 2, &shift, &[c1, c2], 20);
        assert_eq!(summary.present_days, 2);
        assert_eq!(summary.absent_days, 18);
        assert_eq!(summary.overtime_minutes, 30);
    }

    #[test]
    fn summary_ignores_other_employee_and_month() {
        let emp = EmployeeId::new();
        let other = EmployeeId::new();
        let shift = Shift::new("Pagi", 480, 1_020, 10, MON_FRI_MASK, now()).unwrap();
        let d1 = BusinessDate::parse("2026-02-02").unwrap();
        let d2 = BusinessDate::parse("2026-03-02").unwrap();
        let c1 =
            Checkin::record(other, d1, 480, 1_020, CheckinSource::Manual, None, now()).unwrap();
        let c2 = Checkin::record(emp, d2, 480, 1_020, CheckinSource::Manual, None, now()).unwrap();
        let summary = summarize_month(emp, 2026, 2, &shift, &[c1, c2], 20);
        assert_eq!(summary.present_days, 0);
        assert_eq!(summary.absent_days, 20);
    }
}
