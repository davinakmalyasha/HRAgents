use chrono::{DateTime, Datelike, NaiveDate, TimeZone, Utc};
use chrono_tz::Asia::Jakarta;
use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;

/// The business calendar for this edition. Every "today" in rules, payroll
/// periods, reminders, and retention comes from here — never from the host
/// clock's UTC date.
pub const BUSINESS_TZ: chrono_tz::Tz = Jakarta;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum TimeError {
    #[error("invalid business date {0:?}; expected YYYY-MM-DD")]
    InvalidDate(String),
    #[error("invalid instant {0:?}")]
    InvalidInstant(String),
}

/// A civil date in the business timezone.
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
pub struct BusinessDate(NaiveDate);

impl BusinessDate {
    pub const fn from_naive(date: NaiveDate) -> Self {
        Self(date)
    }

    pub fn parse(value: &str) -> Result<Self, TimeError> {
        NaiveDate::parse_from_str(value, "%Y-%m-%d")
            .map(Self)
            .map_err(|_| TimeError::InvalidDate(value.to_owned()))
    }

    pub fn today() -> Self {
        Self(Utc::now().with_timezone(&BUSINESS_TZ).date_naive())
    }

    pub fn today_at(instant: DateTime<Utc>) -> Self {
        Self(instant.with_timezone(&BUSINESS_TZ).date_naive())
    }

    pub const fn naive(self) -> NaiveDate {
        self.0
    }

    pub fn year(self) -> i32 {
        self.0.year()
    }

    pub fn month(self) -> u32 {
        self.0.month()
    }

    pub fn days_between(self, other: Self) -> i64 {
        (other.0 - self.0).num_days()
    }

    pub fn add_days(self, days: i64) -> Self {
        Self(self.0 + chrono::Duration::days(days))
    }

    /// Working days in the calendar month, weekends only. Public holidays are
    /// operator-maintained and applied by the leave domain, not assumed here.
    pub fn working_days_in_month(self) -> u32 {
        let first = NaiveDate::from_ymd_opt(self.year(), self.month(), 1).expect("valid month");
        let next = if self.month() == 12 {
            NaiveDate::from_ymd_opt(self.year() + 1, 1, 1)
        } else {
            NaiveDate::from_ymd_opt(self.year(), self.month() + 1, 1)
        }
        .expect("valid month");
        (first.iter_days())
            .take_while(|date| *date < next)
            .filter(|date| date.weekday().num_days_from_monday() < 5)
            .count() as u32
    }
}

impl fmt::Display for BusinessDate {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0.format("%Y-%m-%d"))
    }
}

impl FromStr for BusinessDate {
    type Err = TimeError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::parse(s)
    }
}

/// An instant on the UTC timeline. Stored as epoch milliseconds in SQLite and
/// serialized as RFC 3339 with millisecond precision.
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
pub struct UtcInstant(DateTime<Utc>);

impl UtcInstant {
    pub fn now() -> Self {
        Self(Utc::now())
    }

    pub const fn from_datetime(value: DateTime<Utc>) -> Self {
        Self(value)
    }

    pub fn from_millis(millis: i64) -> Result<Self, TimeError> {
        Utc.timestamp_millis_opt(millis)
            .single()
            .map(Self)
            .ok_or_else(|| TimeError::InvalidInstant(millis.to_string()))
    }

    pub fn from_rfc3339(value: &str) -> Result<Self, TimeError> {
        DateTime::parse_from_rfc3339(value)
            .map(|value| Self(value.with_timezone(&Utc)))
            .map_err(|_| TimeError::InvalidInstant(value.to_owned()))
    }

    pub const fn datetime(self) -> DateTime<Utc> {
        self.0
    }

    pub fn millis(self) -> i64 {
        self.0.timestamp_millis()
    }

    pub fn business_date(self) -> BusinessDate {
        BusinessDate::today_at(self.0)
    }

    pub fn plus_seconds(self, seconds: i64) -> Self {
        Self(self.0 + chrono::Duration::seconds(seconds))
    }

    pub fn seconds_since(self, earlier: Self) -> i64 {
        (self.0 - earlier.0).num_seconds()
    }
}

impl fmt::Display for UtcInstant {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}",
            self.0.to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
        )
    }
}

impl FromStr for UtcInstant {
    type Err = TimeError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::from_rfc3339(s)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn business_date_is_jakarta_not_utc() {
        // 2026-12-31T18:30:00Z is already 2027-01-01 in Jakarta.
        let instant = Utc.with_ymd_and_hms(2026, 12, 31, 18, 30, 0).unwrap();
        assert_eq!(BusinessDate::today_at(instant).to_string(), "2027-01-01");
    }

    #[test]
    fn working_days_excludes_weekends() {
        assert_eq!(
            BusinessDate::parse("2026-11-01")
                .unwrap()
                .working_days_in_month(),
            21
        );
    }
}
