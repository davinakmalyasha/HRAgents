use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;

/// Exact money, stored as **sen** (1/100 IDR) in an `i64`.
///
/// The current Python product quantises every monetary value to two decimal
/// places with `ROUND_HALF_UP`. Representing that as integer sen preserves the
/// exact bits end to end: additions are exact, percentages round once with the
/// same rule, and no float ever touches a payslip.
#[derive(
    Debug,
    Default,
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
pub struct Money(i64);

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum MoneyError {
    #[error("monetary amount overflows the supported range")]
    Overflow,
    #[error("{0:?} is not a monetary amount")]
    Invalid(String),
    #[error("division by zero")]
    DivisionByZero,
}

pub type MoneyResult<T> = Result<T, MoneyError>;

impl Money {
    pub const ZERO: Self = Self(0);
    pub const ONE_RUPIAH: Self = Self(100);

    pub const fn from_sen(sen: i64) -> Self {
        Self(sen)
    }

    pub const fn sen(self) -> i64 {
        self.0
    }

    pub fn from_rupiah(rupiah: i64) -> MoneyResult<Self> {
        rupiah
            .checked_mul(100)
            .map(Self)
            .ok_or(MoneyError::Overflow)
    }

    pub fn from_rupiah_str(value: &str) -> MoneyResult<Self> {
        Self::parse(value)
    }

    /// Parse a decimal amount with at most two fractional digits. Thousands
    /// separators (`,` or `.`) are accepted only when the final separator is the
    /// decimal point; a bare integer is rupiah. Rounds half away from zero.
    pub fn parse(value: &str) -> MoneyResult<Self> {
        let cleaned: String = value.chars().filter(|c| !c.is_whitespace()).collect();
        if cleaned.is_empty() {
            return Err(MoneyError::Invalid(value.to_owned()));
        }
        let normalized = if cleaned.contains(',') && cleaned.contains('.') {
            if cleaned.rfind(',') > cleaned.rfind('.') {
                // Indonesian style: 1.234.567,89
                cleaned.replace('.', "").replace(',', ".")
            } else {
                // Anglo style: 1,234,567.89
                cleaned.replace(',', "")
            }
        } else if cleaned.contains(',') {
            let parts: Vec<&str> = cleaned.split(',').collect();
            if parts.len() == 2 && parts[1].len() <= 2 {
                format!("{}.{}", parts[0], parts[1])
            } else {
                cleaned.replace(',', "")
            }
        } else {
            cleaned.clone()
        };

        let negative = normalized.starts_with('-');
        let unsigned = normalized.trim_start_matches(['-', '+']);
        let (whole, fraction) = match unsigned.split_once('.') {
            Some((whole, fraction)) => (whole, fraction),
            None => (unsigned, ""),
        };
        if whole.is_empty() || !whole.chars().all(|c| c.is_ascii_digit()) {
            return Err(MoneyError::Invalid(value.to_owned()));
        }
        if !fraction.chars().all(|c| c.is_ascii_digit()) {
            return Err(MoneyError::Invalid(value.to_owned()));
        }
        let whole: i64 = whole.parse().map_err(|_| MoneyError::Overflow)?;
        let mut cents: i64 = match fraction.len() {
            0 => 0,
            1 => {
                fraction
                    .parse::<i64>()
                    .map_err(|_| MoneyError::Invalid(value.into()))?
                    * 10
            }
            _ => fraction[..2]
                .parse::<i64>()
                .map_err(|_| MoneyError::Invalid(value.into()))?,
        };
        // Round half away from zero on the third fractional digit, matching
        // Python's ROUND_HALF_UP at the Money boundary.
        if fraction.len() > 2 && fraction.as_bytes()[2] >= b'5' {
            cents += 1;
        }
        let total = whole
            .checked_mul(100)
            .and_then(|v| v.checked_add(cents))
            .ok_or(MoneyError::Overflow)?;
        Ok(Self(if negative { -total } else { total }))
    }

    pub fn checked_add(self, other: Self) -> MoneyResult<Self> {
        self.0
            .checked_add(other.0)
            .map(Self)
            .ok_or(MoneyError::Overflow)
    }

    pub fn checked_sub(self, other: Self) -> MoneyResult<Self> {
        self.0
            .checked_sub(other.0)
            .map(Self)
            .ok_or(MoneyError::Overflow)
    }

    pub fn checked_neg(self) -> MoneyResult<Self> {
        self.0.checked_neg().map(Self).ok_or(MoneyError::Overflow)
    }

    pub fn checked_mul_int(self, factor: i64) -> MoneyResult<Self> {
        self.0
            .checked_mul(factor)
            .map(Self)
            .ok_or(MoneyError::Overflow)
    }

    pub fn abs(self) -> MoneyResult<Self> {
        self.0.checked_abs().map(Self).ok_or(MoneyError::Overflow)
    }

    pub fn is_zero(self) -> bool {
        self.0 == 0
    }

    pub fn is_negative(self) -> bool {
        self.0 < 0
    }

    /// Multiply by `numerator / denominator`, rounding half away from zero.
    /// The intermediate is `i128`, so plausible payroll amounts never overflow.
    pub fn mul_ratio(self, numerator: i64, denominator: i64) -> MoneyResult<Self> {
        if denominator == 0 {
            return Err(MoneyError::DivisionByZero);
        }
        let value = i128::from(self.0) * i128::from(numerator);
        let den = i128::from(denominator);
        let rounded = if value >= 0 {
            (value + den / 2) / den
        } else {
            (value - den / 2) / den
        };
        i64::try_from(rounded)
            .map(Self)
            .map_err(|_| MoneyError::Overflow)
    }

    /// Apply a percentage expressed in basis points (10_000 bp = 100%).
    pub fn percent_bp(self, basis_points: i64) -> MoneyResult<Self> {
        self.mul_ratio(basis_points, 10_000)
    }

    pub fn sum<I: IntoIterator<Item = Money>>(amounts: I) -> MoneyResult<Self> {
        amounts
            .into_iter()
            .try_fold(Self::ZERO, |acc, amount| acc.checked_add(amount))
    }

    /// `1_234_567.89` — the canonical wire/storage form, without separators.
    pub fn to_decimal_string(self) -> String {
        let negative = self.0 < 0;
        let absolute = self.0.unsigned_abs();
        let whole = absolute / 100;
        let cents = absolute % 100;
        format!("{}{}.{:02}", if negative { "-" } else { "" }, whole, cents)
    }

    /// `Rp1.234.567,89` for UI and export.
    pub fn format_idr(self) -> String {
        let negative = self.0 < 0;
        let absolute = self.0.unsigned_abs();
        let whole = absolute / 100;
        let cents = absolute % 100;
        let digits = whole.to_string();
        let mut grouped = String::new();
        for (index, ch) in digits.chars().enumerate() {
            if index > 0 && (digits.len() - index).is_multiple_of(3) {
                grouped.push('.');
            }
            grouped.push(ch);
        }
        format!(
            "{}Rp{},{:02}",
            if negative { "-" } else { "" },
            grouped,
            cents
        )
    }
}

impl fmt::Display for Money {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.format_idr())
    }
}

impl FromStr for Money {
    type Err = MoneyError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::parse(s)
    }
}

impl std::ops::Add for Money {
    type Output = Money;

    fn add(self, rhs: Self) -> Self::Output {
        self.checked_add(rhs).expect("money overflow")
    }
}

impl std::ops::Sub for Money {
    type Output = Money;

    fn sub(self, rhs: Self) -> Self::Output {
        self.checked_sub(rhs).expect("money overflow")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_both_separator_styles() {
        assert_eq!(Money::parse("1.234.567,89").unwrap(), Money(123_456_789));
        assert_eq!(Money::parse("1,234,567.89").unwrap(), Money(123_456_789));
        assert_eq!(Money::parse("1500000").unwrap(), Money(150_000_000));
        assert_eq!(Money::parse("-2,5").unwrap(), Money(-250));
    }

    #[test]
    fn rounds_half_away_from_zero() {
        assert_eq!(Money::from_sen(5).mul_ratio(1, 2).unwrap(), Money(3));
        assert_eq!(Money::from_sen(-5).mul_ratio(1, 2).unwrap(), Money(-3));
        assert_eq!(
            Money::from_sen(1_000_000).percent_bp(325).unwrap(),
            Money(32_500)
        );
    }

    #[test]
    fn formats_idr() {
        assert_eq!(Money(123_456_789).format_idr(), "Rp1.234.567,89");
        assert_eq!(Money(-250).format_idr(), "-Rp2,50");
        assert_eq!(Money(0).to_decimal_string(), "0.00");
    }

    #[test]
    fn rounds_input_with_more_than_two_places() {
        assert_eq!(Money::parse("0.125").unwrap(), Money(13));
        assert_eq!(Money::parse("-0.125").unwrap(), Money(-13));
        assert_eq!(Money::parse("12.345").unwrap(), Money(1235));
    }

    #[test]
    fn rejects_nonsense() {
        assert!(Money::parse("").is_err());
        assert!(Money::parse("1.2.3").is_err());
        assert!(Money::parse("abc").is_err());
    }
}
