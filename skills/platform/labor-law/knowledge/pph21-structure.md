---
id: pph21-structure
title: PPh 21 — Employment Income Tax Withholding Structure
tags: [pph21, pajak, ter, ptkp, tax, payroll, law, indonesia]
source: PMK No. 168 Tahun 2023 (TER); DJP rules on PTKP exemptions
verified_on: 2026-10-30
---

# PPh 21 Structure

Source: Peraturan Menteri Keuangan No. 168 Tahun 2023 on monthly effective
rates (TER), with annual reconciliation under DJP rules. Confirm current
brackets against the official DJP text for your case.

## The structure

Income tax on employment is withheld monthly by the employer using
progressive effective-rate brackets applied to gross pay less the personal
exemption (PTKP plus dependent allowances). The year closes with an annual
reconciliation in the early months of the following year. Withholding without
an exemption over-collects every month — the exemption is load-bearing, not
optional.

## Where the numbers live here

Every bracket, rate, and exemption figure is operator data: the verified
`pph21_ter` and `pph21_ptkp` rate tables. Payroll withholds progressively
from those tables and raises a blocking anomaly when the exemption table is
unusable. This note never states a tax figure.

This is a summary of the cited sources for HR orientation, not tax advice
for a specific case — confirm with the operator or a tax consultant.
