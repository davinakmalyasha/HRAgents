---
id: bpjs-structure
title: BPJS — Health and Employment Social Security Structure
tags: [bpjs, bpjs-kesehatan, bpjs-ketenagakerjaan, jht, jkk, jkm, jp, jaminan-sosial, payroll, law, indonesia]
source: UU No. 24 Tahun 2011 tentang BPJS; UU No. 40 Tahun 2004 tentang SJSN
verified_on: 2026-10-30
---

# BPJS Structure

Source: UU No. 24 Tahun 2011 (BPJS) under UU No. 40 Tahun 2004 (SJSN).
Contribution figures change by decree — this note states the structure only.

## The structure

Two agencies. BPJS Kesehatan (health) splits contributions between employer
and employee against a wage cap. BPJS Ketenagakerjaan (employment) runs four
programs: JHT old-age savings (employer and employee shares), JKK
work-accident cover (employer only, risk-class dependent), JKM death cover
(employer only), and JP pension (employer and employee shares against a wage
cap). Employer shares are company cost on top of salary, not deductions.

## Where the numbers live here

Every share, cap, and risk-class row is operator data: the verified
`bpjs_kesehatan`, `bpjs_ketenagakerjaan_jht`, `bpjs_jp`, `bpjs_jkk`, and
`bpjs_jkm` rate tables. Payroll charges the employee's risk class from their
record and blocks when a keyed table has no class for them. This note never
states a contribution figure.

This is a summary of the cited sources for HR orientation, not legal advice
for a specific case — confirm current figures with BPJS for your case.
