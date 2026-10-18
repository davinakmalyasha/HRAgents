"""The generated 50-profile résumé dataset and its format variants.

The plan asks for 18 engineering and 32 non-IT profiles, English and Bahasa
Indonesia mixed, each renderable as Markdown, JSON and PDF. The catalog below
is the dataset: structured facts, not 50 hand-written blobs, so the set stays
consistent and a new profile is a data edit rather than an essay.

``render_markdown`` produces the text the extraction agent reads.
``render_json`` is the structured-import variant (a recruiter exporting from an
ATS). ``render_pdf`` writes a real PDF with a minimal deterministic writer, so
the document-extraction path (pypdf) is exercised against bytes the repository
owns rather than a binary fixture nobody can review.

Everything is ASCII on purpose: the PDF writer embeds Helvetica, and a résumé
that needs an encoding the writer cannot express would fail the variant test for
the wrong reason. Indonesian résumés here are plain Latin script.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

LANG_EN = "en"
LANG_ID = "id"


@dataclass(frozen=True)
class Role:
    title: str
    company: str
    start: str
    end: str
    highlights: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    slug: str
    family: str
    seniority: str
    language: str
    name: str
    city: str
    email: str
    headline: str
    summary: str
    roles: tuple[Role, ...]
    skills: tuple[str, ...]
    education: tuple[str, ...]
    certifications: tuple[str, ...] = ()


def profile(
    slug: str,
    family: str,
    seniority: str,
    language: str,
    name: str,
    city: str,
    headline: str,
    summary: str,
    roles: list[Role],
    skills: list[str],
    education: list[str],
    certifications: list[str] | None = None,
) -> Profile:
    return Profile(
        slug=slug,
        family=family,
        seniority=seniority,
        language=language,
        name=name,
        city=city,
        email=f"{name.split()[0].lower()}@example.com",
        headline=headline,
        summary=summary,
        roles=tuple(roles),
        skills=tuple(skills),
        education=tuple(education),
        certifications=tuple(certifications or ()),
    )


# --- 18 engineering profiles ---------------------------------------------------


def _engineering() -> list[Profile]:
    return [
        profile(
            "budi-backend-en",
            "engineering",
            "senior",
            LANG_EN,
            "Budi Santoso",
            "Jakarta",
            "Backend Engineer",
            "Backend engineer with 8 years building payment and ingestion APIs, "
            "mostly Python and PostgreSQL.",
            [
                Role(
                    "Lead Engineer",
                    "Merdeka AI",
                    "2023-02",
                    "present",
                    (
                        "Led the ingestion rewrite to Kafka; p95 latency fell from 4s to 180ms.",
                        "Owned the API design for the evaluation pipeline and its schema reviews.",
                    ),
                ),
                Role(
                    "Senior Engineer",
                    "Nusantara Systems",
                    "2018-06",
                    "2023-01",
                    (
                        "Built payment APIs in Python and FastAPI used by 40 merchants.",
                        "Introduced queue-based retries and idempotency keys.",
                    ),
                ),
            ],
            ["Python", "FastAPI", "PostgreSQL", "Redis", "Kafka", "Docker", "Kubernetes"],
            ["2014-2018 Universitas Indonesia, Computer Science"],
        ),
        profile(
            "sari-backend-id",
            "engineering",
            "mid",
            LANG_ID,
            "Sari Wulandari",
            "Bandung",
            "Backend Engineer",
            "Backend engineer dengan 5 tahun pengalaman di layanan keuangan, "
            "terbiasa Python dan desain basis data.",
            [
                Role(
                    "Backend Engineer",
                    "PT Sinar Digital",
                    "2021-03",
                    "sekarang",
                    (
                        "Mengembangkan API pembayaran dengan Python dan PostgreSQL.",
                        "Menurunkan waktu respons endpoint laporan dari 2 detik ke 300 ms.",
                    ),
                ),
                Role(
                    "Junior Engineer",
                    "CV Media Kita",
                    "2019-07",
                    "2021-02",
                    ("Membangun layanan notifikasi dan integrasi email.",),
                ),
            ],
            ["Python", "Django", "PostgreSQL", "Redis", "Git", "Linux"],
            ["2015-2019 Institut Teknologi Bandung, Teknik Informatika"],
        ),
        profile(
            "arif-frontend-en",
            "engineering",
            "senior",
            LANG_EN,
            "Arif Hidayat",
            "Jakarta",
            "Frontend Engineer",
            "Frontend engineer focused on accessible, fast product surfaces; "
            "seven years with React and TypeScript.",
            [
                Role(
                    "Staff Frontend Engineer",
                    "Toko Pintar",
                    "2022-01",
                    "present",
                    (
                        "Rebuilt checkout in React and TypeScript; conversion rose 9%.",
                        "Set the accessibility baseline shared by four squads.",
                    ),
                ),
                Role(
                    "Frontend Engineer",
                    "Ruang Kerja",
                    "2018-04",
                    "2021-12",
                    ("Delivered the admin dashboard and its design tokens.",),
                ),
            ],
            ["TypeScript", "React", "Next.js", "Tailwind CSS", "Testing Library", "Playwright"],
            ["2013-2017 Universitas Gadjah Mada, Ilmu Komputer"],
        ),
        profile(
            "dewi-frontend-id",
            "engineering",
            "mid",
            LANG_ID,
            "Dewi Anggraini",
            "Yogyakarta",
            "Frontend Engineer",
            "Frontend engineer dengan fokus aksesibilitas dan performa, empat tahun memakai React.",
            [
                Role(
                    "Frontend Engineer",
                    "PT Karya Nusantara",
                    "2022-05",
                    "sekarang",
                    (
                        "Membangun ulang halaman katalog dengan React dan TypeScript.",
                        "Menerapkan uji aksesibilitas otomatis di pipeline CI.",
                    ),
                ),
                Role(
                    "Web Developer",
                    "Studio Kreatif Jogja",
                    "2020-08",
                    "2022-04",
                    ("Mengerjakan situs klien dengan fokus performa dan SEO.",),
                ),
            ],
            ["JavaScript", "React", "TypeScript", "CSS", "Figma", "Git"],
            ["2016-2020 Universitas Islam Indonesia, Teknik Informatika"],
        ),
        profile(
            "fajar-fullstack-en",
            "engineering",
            "senior",
            LANG_EN,
            "Fajar Nugroho",
            "Surabaya",
            "Full-stack Engineer",
            "Full-stack engineer who ships small teams end to end: schema, API, "
            "interface and the deploy.",
            [
                Role(
                    "Full-stack Engineer",
                    "Logistik Cepat",
                    "2021-09",
                    "present",
                    (
                        "Built the driver app backend and dispatch console with FastAPI and Vue.",
                        "Cut deploy time from 40 to 6 minutes with containerised pipelines.",
                    ),
                ),
                Role(
                    "Software Engineer",
                    "PT Delta Teknologi",
                    "2017-02",
                    "2021-08",
                    ("Maintained a Django monolith and its PostgreSQL schema.",),
                ),
            ],
            ["Python", "FastAPI", "Vue", "PostgreSQL", "Docker", "CI/CD"],
            ["2012-2016 Institut Teknologi Sepuluh Nopember, Teknik Komputer"],
        ),
        profile(
            "intan-fullstack-id",
            "engineering",
            "mid",
            LANG_ID,
            "Intan Permata",
            "Jakarta",
            "Full-stack Engineer",
            "Full-stack engineer dengan pengalaman produk B2B, terbiasa "
            "menghubungkan API dan antarmuka.",
            [
                Role(
                    "Software Engineer",
                    "PT Solusi Bisnis",
                    "2021-11",
                    "sekarang",
                    (
                        "Mengembangkan modul penagihan dengan Laravel dan Vue.",
                        "Menulis uji integrasi untuk alur pembayaran berulang.",
                    ),
                ),
                Role(
                    "Junior Developer",
                    "Startup Gerak",
                    "2019-06",
                    "2021-10",
                    ("Membantu migrasi data pelanggan ke PostgreSQL.",),
                ),
            ],
            ["PHP", "Laravel", "Vue", "PostgreSQL", "Redis", "Git"],
            ["2015-2019 Universitas Airlangga, Sistem Informasi"],
        ),
        profile(
            "rizal-mobile-en",
            "engineering",
            "senior",
            LANG_EN,
            "Rizal Mahendra",
            "Jakarta",
            "Mobile Engineer",
            "Mobile engineer with six years of Android and Kotlin, one shipped "
            "iOS app, and a habit of measuring before optimising.",
            [
                Role(
                    "Senior Android Engineer",
                    "Bank Kita",
                    "2022-03",
                    "present",
                    (
                        "Led the Kotlin migration of the mobile banking app.",
                        "Reduced cold start from 3.1s to 1.4s with baseline profiles.",
                    ),
                ),
                Role(
                    "Android Developer",
                    "Aplikasi Harian",
                    "2018-01",
                    "2022-02",
                    ("Shipped three consumer apps and their release pipelines.",),
                ),
            ],
            ["Kotlin", "Android", "Jetpack Compose", "Swift", "REST", "Firebase"],
            ["2013-2017 Universitas Brawijaya, Teknik Informatika"],
        ),
        profile(
            "putri-mobile-id",
            "engineering",
            "mid",
            LANG_ID,
            "Putri Handayani",
            "Bandung",
            "Mobile Engineer",
            "Mobile engineer dengan pengalaman Flutter dan Android, fokus pada kualitas rilis.",
            [
                Role(
                    "Mobile Engineer",
                    "PT Mobile Cerdas",
                    "2021-04",
                    "sekarang",
                    (
                        "Mengembangkan aplikasi Flutter untuk 50 ribu pengguna aktif.",
                        "Menyiapkan pipeline rilis otomatis dan pemantauan crash.",
                    ),
                ),
                Role(
                    "Android Developer",
                    "Studio Aplikasi",
                    "2019-09",
                    "2021-03",
                    ("Membangun aplikasi katalog dan integrasi pembayaran.",),
                ),
            ],
            ["Flutter", "Dart", "Kotlin", "Android", "Firebase", "Git"],
            ["2015-2019 Politeknik Negeri Bandung, Teknik Informatika"],
        ),
        profile(
            "yoga-data-en",
            "engineering",
            "senior",
            LANG_EN,
            "Yoga Pratama",
            "Jakarta",
            "Data Engineer",
            "Data engineer who builds the boring pipelines everybody relies on: "
            "warehouse models, orchestration, and contracts between teams.",
            [
                Role(
                    "Data Engineer",
                    "Analitika Nusantara",
                    "2020-10",
                    "present",
                    (
                        "Built the warehouse on PostgreSQL and dbt; 60 models under test.",
                        "Cut nightly batch time by half with incremental loads.",
                    ),
                ),
                Role(
                    "ETL Developer",
                    "PT Data Prima",
                    "2017-05",
                    "2020-09",
                    ("Maintained Airflow DAGs feeding finance and operations reports.",),
                ),
            ],
            ["Python", "SQL", "dbt", "Airflow", "PostgreSQL", "Spark"],
            ["2012-2016 Universitas Indonesia, Statistika"],
        ),
        profile(
            "melati-data-id",
            "engineering",
            "mid",
            LANG_ID,
            "Melati Kusuma",
            "Jakarta",
            "Data Engineer",
            "Data engineer dengan pengalaman membangun pipeline analitik dan tata kelola data.",
            [
                Role(
                    "Data Engineer",
                    "PT Analitik Cerdas",
                    "2022-01",
                    "sekarang",
                    (
                        "Membangun pipeline harian dengan Airflow dan PostgreSQL.",
                        "Mendokumentasikan kamus data untuk tim produk.",
                    ),
                ),
                Role(
                    "Analis Data",
                    "CV Insight",
                    "2020-02",
                    "2021-12",
                    ("Menyusun laporan otomatis untuk manajemen.",),
                ),
            ],
            ["Python", "SQL", "Airflow", "PostgreSQL", "Metabase"],
            ["2016-2020 Universitas Bina Nusantara, Sistem Informasi"],
        ),
        profile(
            "dimas-devops-en",
            "engineering",
            "senior",
            LANG_EN,
            "Dimas Saputra",
            "Jakarta",
            "DevOps Engineer",
            "DevOps engineer with seven years keeping small teams shipping: "
            "infrastructure as code, observability, and on-call that people survive.",
            [
                Role(
                    "DevOps Lead",
                    "Cloud Merdeka",
                    "2021-06",
                    "present",
                    (
                        "Moved 20 services to Kubernetes with Terraform and GitHub Actions.",
                        "Introduced SLOs and alerting; page volume dropped by 70%.",
                    ),
                ),
                Role(
                    "Systems Engineer",
                    "PT Infrastruktur",
                    "2016-08",
                    "2021-05",
                    ("Ran CI servers, backups and the migration to cloud VMs.",),
                ),
            ],
            ["Terraform", "Kubernetes", "Docker", "AWS", "Prometheus", "Bash", "Go"],
            ["2012-2016 Universitas Diponegoro, Teknik Komputer"],
        ),
        profile(
            "agus-devops-id",
            "engineering",
            "mid",
            LANG_ID,
            "Agus Setiawan",
            "Surabaya",
            "DevOps Engineer",
            "DevOps engineer dengan pengalaman otomasi rilis dan pemantauan.",
            [
                Role(
                    "DevOps Engineer",
                    "PT Server Nusantara",
                    "2021-08",
                    "sekarang",
                    (
                        "Mengelola Kubernetes dan pipeline rilis untuk 12 layanan.",
                        "Menyusun runbook insiden dan uji pemulihan.",
                    ),
                ),
                Role(
                    "System Administrator",
                    "CV Jaringan",
                    "2018-03",
                    "2021-07",
                    ("Memelihara server Linux dan basis data.",),
                ),
            ],
            ["Linux", "Docker", "Kubernetes", "Ansible", "Bash", "PostgreSQL"],
            ["2014-2018 Politeknik Elektronika Surabaya, Teknik Informatika"],
        ),
        profile(
            "nadia-qa-en",
            "engineering",
            "mid",
            LANG_EN,
            "Nadia Rahmawati",
            "Jakarta",
            "QA Engineer",
            "QA engineer who prefers regression suites to heroics: API contracts, "
            "accessible UI checks, and failures that reproduce.",
            [
                Role(
                    "QA Engineer",
                    "Toko Pintar",
                    "2021-02",
                    "present",
                    (
                        "Built the API regression suite in Playwright and pytest.",
                        "Embedded accessibility checks in the pull-request pipeline.",
                    ),
                ),
                Role(
                    "Test Analyst",
                    "PT Kualitas",
                    "2018-09",
                    "2021-01",
                    ("Wrote manual test plans for e-commerce releases.",),
                ),
            ],
            ["Playwright", "pytest", "API testing", "SQL", "Postman"],
            ["2014-2018 Universitas Padjadjaran, Teknik Informatika"],
        ),
        profile(
            "bayu-qa-id",
            "engineering",
            "junior",
            LANG_ID,
            "Bayu Firmansyah",
            "Semarang",
            "QA Engineer",
            "QA engineer awal karier dengan disiplin dokumentasi dan rasa ingin tahu pada otomasi.",
            [
                Role(
                    "QA Engineer",
                    "PT Rilis Cepat",
                    "2023-01",
                    "sekarang",
                    (
                        "Menulis skenario uji fungsional untuk aplikasi web.",
                        "Membantu memelihara suite uji regresi berbasis Playwright.",
                    ),
                ),
                Role(
                    "Intern QA",
                    "Startup Semarang",
                    "2022-06",
                    "2022-12",
                    ("Menguji fitur pembayaran dan mencatat cacat dengan bukti.",),
                ),
            ],
            ["Manual testing", "Playwright", "SQL", "Jira", "Git"],
            ["2018-2022 Universitas Diponegoro, Sistem Informasi"],
        ),
        profile(
            "citra-ml-en",
            "engineering",
            "senior",
            LANG_EN,
            "Citra Lestari",
            "Jakarta",
            "Machine Learning Engineer",
            "ML engineer who ships retrieval and ranking systems with measured quality, not demos.",
            [
                Role(
                    "Senior ML Engineer",
                    "Merdeka AI",
                    "2022-04",
                    "present",
                    (
                        "Built a hybrid retrieval service with pgvector and reranking.",
                        "Defined offline evaluation sets and the release gate for model changes.",
                    ),
                ),
                Role(
                    "Data Scientist",
                    "PT Prediksi",
                    "2018-02",
                    "2022-03",
                    (
                        "Built demand forecasting models used in weekly planning.",
                        "Documented feature pipelines and evaluation protocols.",
                    ),
                ),
            ],
            ["Python", "PyTorch", "scikit-learn", "pgvector", "NLP", "MLOps"],
            ["2013-2017 Institut Teknologi Bandung, Matematika"],
        ),
        profile(
            "hendra-backend-id",
            "engineering",
            "junior",
            LANG_ID,
            "Hendra Gunawan",
            "Medan",
            "Backend Engineer",
            "Backend engineer awal karier dengan dasar kuat di Python dan SQL.",
            [
                Role(
                    "Backend Developer",
                    "PT Digital Medan",
                    "2022-09",
                    "sekarang",
                    (
                        "Mengembangkan endpoint layanan pelanggan dengan Django.",
                        "Menulis uji unit dan integrasi untuk modul penagihan.",
                    ),
                ),
                Role(
                    "Magang Developer",
                    "CV Teknologi Lokal",
                    "2021-12",
                    "2022-08",
                    ("Membantu pemeliharaan aplikasi internal.",),
                ),
            ],
            ["Python", "Django", "SQL", "Git", "Postman"],
            ["2018-2022 Universitas Sumatera Utara, Ilmu Komputer"],
        ),
        profile(
            "lina-frontend-id",
            "engineering",
            "mid",
            LANG_ID,
            "Lina Marlina",
            "Bekasi",
            "Frontend Engineer",
            "Frontend engineer dengan pengalaman aplikasi internal dan komponen "
            "yang dipakai ulang.",
            [
                Role(
                    "Frontend Developer",
                    "PT Manufaktur Digital",
                    "2021-05",
                    "sekarang",
                    (
                        "Membangun dasbor operasional dengan Vue dan TypeScript.",
                        "Menyatukan komponen tabel dan formulir lintas modul.",
                    ),
                ),
                Role(
                    "Web Developer",
                    "Agensi Kreatif",
                    "2019-04",
                    "2021-04",
                    ("Mengerjakan situs perusahaan dan landing page kampanye.",),
                ),
            ],
            ["Vue", "TypeScript", "JavaScript", "CSS", "Git"],
            ["2015-2019 Universitas Gunadarma, Teknik Informatika"],
        ),
        profile(
            "raka-backend-en",
            "engineering",
            "senior",
            LANG_EN,
            "Raka Aditya",
            "Jakarta",
            "Backend Engineer",
            "Backend engineer with deep PostgreSQL experience and a preference for "
            "small services and explicit contracts.",
            [
                Role(
                    "Principal Engineer",
                    "Platform Andalan",
                    "2020-07",
                    "present",
                    (
                        "Designed the multi-tenant schema and row-level security model.",
                        "Mentored four engineers through their first production migrations.",
                    ),
                ),
                Role(
                    "Backend Engineer",
                    "PT Aplikasi Bisnis",
                    "2015-03",
                    "2020-06",
                    (
                        "Built billing and reporting services in Python.",
                        "Introduced database migrations and schema reviews.",
                    ),
                ),
            ],
            ["Python", "PostgreSQL", "SQLAlchemy", "FastAPI", "Docker"],
            ["2011-2015 Universitas Indonesia, Ilmu Komputer"],
        ),
    ]


# --- 32 non-IT profiles --------------------------------------------------------


def _finance() -> list[Profile]:
    return [
        profile(
            "ayu-finance-id",
            "finance",
            "senior",
            LANG_ID,
            "Ayu Lestari",
            "Jakarta",
            "Finance Staff",
            "Staf keuangan dengan tujuh tahun pengalaman pada penutupan bulanan, "
            "rekonsiliasi, dan pelaporan pajak.",
            [
                Role(
                    "Finance Staff",
                    "PT Sumber Makmur",
                    "2019-02",
                    "sekarang",
                    (
                        "Menutup buku bulanan dan merekonsiliasi bank untuk tiga entitas.",
                        "Menyiapkan pelaporan PPh 21 dan e-Faktur.",
                    ),
                ),
                Role(
                    "Accounting Staff",
                    "CV Sejahtera",
                    "2016-01",
                    "2019-01",
                    ("Mencatat jurnal harian dan membantu audit tahunan.",),
                ),
            ],
            ["Accurate", "Microsoft Excel", "SAP", "PPh 21", "e-Faktur", "Rekonsiliasi bank"],
            ["2012-2016 Universitas Trisakti, Akuntansi"],
            ["Brevet A dan B"],
        ),
        profile(
            "rina-accounting-en",
            "finance",
            "mid",
            LANG_EN,
            "Rina Kartika",
            "Jakarta",
            "Accountant",
            "Accountant with five years across accounts payable, fixed assets and "
            "month-end close for a distribution business.",
            [
                Role(
                    "Accountant",
                    "Gudang Digital",
                    "2021-04",
                    "present",
                    (
                        "Owned the month-end close in SAP B1 with a five-day deadline.",
                        "Reconciled payable balances across 120 suppliers.",
                    ),
                ),
                Role(
                    "AP Officer",
                    "PT Distribusi",
                    "2019-06",
                    "2021-03",
                    ("Processed invoices and prepared weekly payment batches.",),
                ),
            ],
            ["SAP B1", "Excel", "Accounts payable", "Fixed assets", "PSAK"],
            ["2015-2019 Universitas Katolik Indonesia Atma Jaya, Akuntansi"],
        ),
        profile(
            "taufik-audit-id",
            "finance",
            "senior",
            LANG_ID,
            "Taufik Hidayat",
            "Jakarta",
            "Internal Auditor",
            "Auditor internal dengan pengalaman audit operasional dan kepatuhan pada "
            "perusahaan manufaktur.",
            [
                Role(
                    "Internal Audit Supervisor",
                    "PT Manufaktur Jaya",
                    "2018-03",
                    "sekarang",
                    (
                        "Memimpin audit siklus persediaan dan pengadaan.",
                        "Menyusun temuan dan memantau rencana tindak lanjut.",
                    ),
                ),
                Role(
                    "Audit Associate",
                    "KAP Prima",
                    "2013-08",
                    "2018-02",
                    ("Mengaudit laporan keuangan klien menengah.",),
                ),
            ],
            ["Audit internal", "Pengendalian internal", "Excel", "PSAK", "Manajemen risiko"],
            ["2009-2013 Universitas Padjadjaran, Akuntansi"],
            ["CPA"],
        ),
        profile(
            "sinta-tax-en",
            "finance",
            "senior",
            LANG_EN,
            "Sinta Maharani",
            "Jakarta",
            "Tax Specialist",
            "Tax specialist with six years on corporate income tax, VAT filings and tax audits.",
            [
                Role(
                    "Tax Specialist",
                    "Konsultan Pajak Andalan",
                    "2019-07",
                    "present",
                    (
                        "Prepared annual corporate tax returns for 20 clients.",
                        "Represented clients through routine tax audits.",
                    ),
                ),
                Role(
                    "Tax Staff",
                    "PT Niaga",
                    "2017-02",
                    "2019-06",
                    ("Handled monthly VAT and withholding filings.",),
                ),
            ],
            ["PPh badan", "PPN", "e-Faktur", "Tax audit", "Excel"],
            ["2013-2017 Universitas Indonesia, Akuntansi"],
            ["Brevet A dan B", "USKP"],
        ),
        profile(
            "wawan-fpa-id",
            "finance",
            "senior",
            LANG_ID,
            "Wawan Saputra",
            "Tangerang",
            "FP&A Analyst",
            "Analis FP&A dengan pengalaman penyusunan anggaran, analisis varians, dan "
            "model keuangan.",
            [
                Role(
                    "Senior FP&A Analyst",
                    "PT Fast Moving",
                    "2020-01",
                    "sekarang",
                    (
                        "Menyusun anggaran tahunan dan proyeksi triwulanan.",
                        "Menganalisis varians biaya produksi dan menyajikan ke manajemen.",
                    ),
                ),
                Role(
                    "Finance Analyst",
                    "CV Ritel Modern",
                    "2016-05",
                    "2019-12",
                    ("Membangun model keuangan untuk pembukaan gerai baru.",),
                ),
            ],
            ["Financial modeling", "Excel", "Budgeting", "Variance analysis", "Power BI"],
            ["2012-2016 Universitas Bina Nusantara, Keuangan"],
        ),
        profile(
            "lisa-bookkeeping-en",
            "finance",
            "junior",
            LANG_EN,
            "Lisa Puspita",
            "Bandung",
            "Bookkeeper",
            "Bookkeeper early in her career with careful records and a fast month-end.",
            [
                Role(
                    "Bookkeeper",
                    "Klinik Sehat Bersama",
                    "2022-08",
                    "present",
                    (
                        "Maintained daily journals and supplier ledgers.",
                        "Prepared monthly reports for the clinic owner.",
                    ),
                ),
                Role(
                    "Admin Finance Intern",
                    "CV Bersinar",
                    "2021-09",
                    "2022-07",
                    ("Assisted invoicing and expense reconciliation.",),
                ),
            ],
            ["Excel", "Accurate", "Journal entries", "Invoicing"],
            ["2018-2022 Universitas Pendidikan Indonesia, Akuntansi"],
        ),
        profile(
            "yusuf-credit-id",
            "finance",
            "mid",
            LANG_ID,
            "Yusuf Ramadhan",
            "Surabaya",
            "Credit Analyst",
            "Analis kredit dengan pengalaman penilaian risiko usaha kecil dan menengah.",
            [
                Role(
                    "Credit Analyst",
                    "Bank Daerah",
                    "2020-04",
                    "sekarang",
                    (
                        "Menganalisis laporan keuangan calon debitur UMKM.",
                        "Menyusun rekomendasi kredit dan memantau portofolio.",
                    ),
                ),
                Role(
                    "Loan Officer",
                    "Koperasi Maju",
                    "2017-09",
                    "2020-03",
                    ("Memproses pengajuan pinjaman dan verifikasi dokumen.",),
                ),
            ],
            ["Analisis kredit", "Laporan keuangan", "Excel", "Manajemen risiko"],
            ["2013-2017 Universitas Airlangga, Manajemen"],
        ),
        profile(
            "mega-accounting-en",
            "finance",
            "senior",
            LANG_EN,
            "Mega Anjani",
            "Jakarta",
            "Accounting Manager",
            "Accounting manager who has owned close, consolidation and the audit "
            "relationship for a group of three entities.",
            [
                Role(
                    "Accounting Manager",
                    "Group Tiga Roda",
                    "2019-11",
                    "present",
                    (
                        "Ran consolidated reporting for three entities under PSAK.",
                        "Led the annual audit to an unqualified opinion three years running.",
                    ),
                ),
                Role(
                    "Senior Accountant",
                    "PT Roda Jaya",
                    "2014-02",
                    "2019-10",
                    ("Owned close and revenue recognition for the services arm.",),
                ),
            ],
            ["Consolidation", "PSAK", "SAP", "Excel", "Audit coordination"],
            ["2010-2014 Universitas Trisakti, Akuntansi"],
            ["CPA"],
        ),
    ]


def _people_ops() -> list[Profile]:
    return [
        profile(
            "eka-hr-id",
            "hr",
            "senior",
            LANG_ID,
            "Eka Putri",
            "Jakarta",
            "HR Generalist",
            "HR generalist dengan pengalaman rekrutmen, administrasi karyawan, dan "
            "hubungan industrial.",
            [
                Role(
                    "HR Generalist",
                    "PT Sumber Daya",
                    "2019-03",
                    "sekarang",
                    (
                        "Mengelola siklus rekrutmen untuk 30 posisi per tahun.",
                        "Menangani administrasi karyawan dan kepatuhan BPJS.",
                    ),
                ),
                Role(
                    "HR Admin",
                    "CV Mandiri",
                    "2016-06",
                    "2019-02",
                    ("Mengurus kontrak, absensi, dan penggajian dasar.",),
                ),
            ],
            ["Rekrutmen", "Administrasi HR", "BPJS", "UU Ketenagakerjaan", "Excel"],
            ["2012-2016 Universitas Indonesia, Psikologi"],
        ),
        profile(
            "dian-hr-en",
            "hr",
            "mid",
            LANG_EN,
            "Dian Permatasari",
            "Jakarta",
            "People Operations Specialist",
            "People operations specialist focused on onboarding, records and the "
            "small details that make a first week work.",
            [
                Role(
                    "People Operations Specialist",
                    "Startup Tumbuh",
                    "2021-06",
                    "present",
                    (
                        "Owned onboarding for 60 hires across two years.",
                        "Maintained the HRIS records and document compliance.",
                    ),
                ),
                Role(
                    "HR Coordinator",
                    "PT Karya Baru",
                    "2019-01",
                    "2021-05",
                    ("Coordinated interviews, offers and onboarding logistics.",),
                ),
            ],
            ["Onboarding", "HRIS", "Document management", "Excel", "English"],
            ["2015-2019 Universitas Katolik Indonesia Atma Jaya, Psikologi"],
        ),
        profile(
            "putra-admin-id",
            "hr",
            "junior",
            LANG_ID,
            "Putra Wijaya",
            "Bekasi",
            "Office Administrator",
            "Administrator kantor dengan pengalaman pengadaan kecil, penjadwalan, dan "
            "dukungan tim.",
            [
                Role(
                    "Office Administrator",
                    "PT Kantor Kita",
                    "2022-03",
                    "sekarang",
                    (
                        "Mengelola pengadaan ATK dan kebutuhan kantor.",
                        "Menjadwalkan rapat dan mengelola aset kantor.",
                    ),
                ),
                Role(
                    "Admin Support",
                    "CV Aneka Usaha",
                    "2021-01",
                    "2022-02",
                    ("Membantu administrasi penjualan dan arsip.",),
                ),
            ],
            ["Microsoft Office", "Pengadaan", "Penjadwalan", "Arsip"],
            ["2018-2021 Universitas Islam Negeri Jakarta, Administrasi"],
        ),
        profile(
            "nia-recruiter-en",
            "hr",
            "mid",
            LANG_EN,
            "Nia Kurniawati",
            "Surabaya",
            "Technical Recruiter",
            "Technical recruiter who runs structured interviews and keeps candidates "
            "informed without flooding them.",
            [
                Role(
                    "Technical Recruiter",
                    "Platform Andalan",
                    "2021-02",
                    "present",
                    (
                        "Hired 25 engineers in two years across backend and mobile.",
                        "Introduced structured scorecards for every interview loop.",
                    ),
                ),
                Role(
                    "Recruiter",
                    "Agensi Talenta",
                    "2018-08",
                    "2021-01",
                    ("Sourced and screened candidates for finance and technology clients.",),
                ),
            ],
            ["Sourcing", "Structured interviews", "ATS", "Employer branding"],
            ["2014-2018 Universitas Airlangga, Psikologi"],
        ),
    ]


def _sales() -> list[Profile]:
    return [
        profile(
            "adi-sales-id",
            "sales",
            "senior",
            LANG_ID,
            "Adi Nugroho",
            "Surabaya",
            "Sales Manager",
            "Manajer penjualan dengan pengalaman membangun tim dan saluran distribusi "
            "di Jawa Timur.",
            [
                Role(
                    "Area Sales Manager",
                    "PT Consumer Jaya",
                    "2018-05",
                    "sekarang",
                    (
                        "Memimpin 12 tenaga penjualan dan distributor regional.",
                        "Menumbuhkan penjualan wilayah 35% dalam dua tahun.",
                    ),
                ),
                Role(
                    "Sales Supervisor",
                    "CV Sinar Niaga",
                    "2014-01",
                    "2018-04",
                    ("Mengelola kunjungan rutin dan target bulanan.",),
                ),
            ],
            ["Sales management", "Distribusi", "Negosiasi", "Peramalan penjualan"],
            ["2010-2014 Universitas Brawijaya, Manajemen"],
        ),
        profile(
            "gusti-sales-en",
            "sales",
            "mid",
            LANG_EN,
            "Gusti Ayu",
            "Denpasar",
            "Account Executive",
            "Account executive in hospitality software, closing mid-market deals in "
            "Bali and Lombok.",
            [
                Role(
                    "Account Executive",
                    "Hoteltech Asia",
                    "2021-03",
                    "present",
                    (
                        "Closed 40 mid-market subscriptions across two years.",
                        "Built the partner channel with local consultants.",
                    ),
                ),
                Role(
                    "Business Development",
                    "PT Bali Digital",
                    "2019-01",
                    "2021-02",
                    ("Generated and qualified inbound leads for the resort segment.",),
                ),
            ],
            ["B2B sales", "CRM", "Negotiation", "English", "Hospitality"],
            ["2015-2019 Universitas Udayana, Manajemen"],
        ),
        profile(
            "rini-account-exec-id",
            "sales",
            "junior",
            LANG_ID,
            "Rini Astuti",
            "Jakarta",
            "Account Executive",
            "Account executive awal karier dengan fokus pada kebutuhan pelanggan dan "
            "tindak lanjut yang rapi.",
            [
                Role(
                    "Account Executive",
                    "PT Solusi Kantor",
                    "2022-06",
                    "sekarang",
                    (
                        "Mengelola 60 akun pelanggan usaha kecil.",
                        "Mencapai target kuartalan selama tiga kuartal berturut-turut.",
                    ),
                ),
                Role(
                    "Sales Admin",
                    "CV Mitra Bisnis",
                    "2021-02",
                    "2022-05",
                    ("Menyiapkan penawaran dan menindaklanjuti pesanan.",),
                ),
            ],
            ["Penjualan", "CRM", "Negosiasi", "Excel"],
            ["2018-2021 Universitas Mercu Buana, Manajemen"],
        ),
        profile(
            "tony-bizdev-en",
            "sales",
            "senior",
            LANG_EN,
            "Tony Halim",
            "Jakarta",
            "Business Development Manager",
            "Business development manager who opens new segments and builds the "
            "partnerships that keep them.",
            [
                Role(
                    "Business Development Manager",
                    "Logistik Cepat",
                    "2020-02",
                    "present",
                    (
                        "Opened the B2B fulfilment segment; 18 enterprise accounts.",
                        "Negotiated partnership terms with three last-mile providers.",
                    ),
                ),
                Role(
                    "Key Account Manager",
                    "PT Distribusi Modern",
                    "2015-06",
                    "2020-01",
                    ("Managed retail chain accounts and joint business plans.",),
                ),
            ],
            ["Business development", "Partnerships", "Negotiation", "Forecasting"],
            ["2011-2015 Universitas Pelita Harapan, Bisnis"],
        ),
    ]


def _operations() -> list[Profile]:
    return [
        profile(
            "bayu-ops-id",
            "operations",
            "senior",
            LANG_ID,
            "Bayu Perkasa",
            "Karawang",
            "Operations Manager",
            "Manajer operasi pabrik dengan pengalaman produksi, K3, dan perbaikan berkelanjutan.",
            [
                Role(
                    "Operations Manager",
                    "PT Manufaktur Jaya",
                    "2017-08",
                    "sekarang",
                    (
                        "Mengelola lini produksi dengan 120 operator.",
                        "Menurunkan cacat produk 22% melalui perbaikan proses.",
                    ),
                ),
                Role(
                    "Production Supervisor",
                    "PT Manufaktur Jaya",
                    "2012-03",
                    "2017-07",
                    ("Mengawasi jadwal produksi dan keselamatan kerja.",),
                ),
            ],
            ["Manajemen produksi", "K3", "Lean manufacturing", "Perencanaan kapasitas"],
            ["2008-2012 Universitas Singaperbangsa, Teknik Industri"],
            ["Ahli K3 Umum"],
        ),
        profile(
            "husna-logistics-en",
            "operations",
            "mid",
            LANG_EN,
            "Husna Fadillah",
            "Jakarta",
            "Logistics Coordinator",
            "Logistics coordinator who keeps warehouses and freight forwarders on the same page.",
            [
                Role(
                    "Logistics Coordinator",
                    "Gudang Digital",
                    "2021-05",
                    "present",
                    (
                        "Coordinated inbound freight for three warehouses.",
                        "Reduced average dock-to-stock time by two days.",
                    ),
                ),
                Role(
                    "Warehouse Admin",
                    "PT Gudang Nusantara",
                    "2019-02",
                    "2021-04",
                    ("Maintained stock records and shipment documentation.",),
                ),
            ],
            ["Logistics", "Warehouse management", "Excel", "Freight forwarding"],
            ["2015-2019 Universitas Tarumanagara, Manajemen"],
        ),
        profile(
            "edi-warehouse-id",
            "operations",
            "junior",
            LANG_ID,
            "Edi Susanto",
            "Cikarang",
            "Warehouse Supervisor",
            "Supervisor gudang dengan pengalaman penerimaan, penyimpanan, dan "
            "ketepatan pengiriman.",
            [
                Role(
                    "Warehouse Supervisor",
                    "PT Ritel Gudang",
                    "2022-01",
                    "sekarang",
                    (
                        "Mengawasi shift penerimaan dan pengeluaran barang.",
                        "Menerapkan pengecekan stok harian untuk mengurangi selisih.",
                    ),
                ),
                Role(
                    "Staff Gudang",
                    "CV Logistik Lokal",
                    "2020-03",
                    "2021-12",
                    ("Menangani picking, packing, dan dokumen pengiriman.",),
                ),
            ],
            ["Manajemen gudang", "Stok opname", "Forklift", "Excel"],
            ["2016-2020 SMK Negeri Cikarang, Logistik"],
        ),
        profile(
            "vera-procurement-en",
            "operations",
            "senior",
            LANG_EN,
            "Vera Anggraini",
            "Jakarta",
            "Procurement Specialist",
            "Procurement specialist with six years negotiating indirect spend and "
            "keeping suppliers honest.",
            [
                Role(
                    "Procurement Specialist",
                    "Bank Kita",
                    "2020-09",
                    "present",
                    (
                        "Negotiated IT and facilities contracts worth 40 billion rupiah.",
                        "Built the supplier review and renewal calendar.",
                    ),
                ),
                Role(
                    "Purchasing Officer",
                    "PT Sarana Kantor",
                    "2016-04",
                    "2020-08",
                    ("Ran purchase orders and delivery follow-ups for 200 suppliers.",),
                ),
            ],
            ["Procurement", "Negotiation", "Contract management", "Excel", "SAP"],
            ["2012-2016 Universitas Trisakti, Manajemen"],
        ),
    ]


def _service() -> list[Profile]:
    return [
        profile(
            "amelia-cs-id",
            "customer_service",
            "mid",
            LANG_ID,
            "Amelia Sari",
            "Jakarta",
            "Customer Service Team Lead",
            "Team lead layanan pelanggan dengan pengalaman menangani keluhan dan "
            "menjaga kualitas jawaban.",
            [
                Role(
                    "Customer Service Team Lead",
                    "Toko Pintar",
                    "2020-11",
                    "sekarang",
                    (
                        "Memimpin tim 10 agen untuk saluran chat dan telepon.",
                        "Menurunkan waktu tanggap pertama menjadi di bawah 5 menit.",
                    ),
                ),
                Role(
                    "Customer Service Agent",
                    "CV Belanja Cepat",
                    "2017-04",
                    "2020-10",
                    ("Menangani keluhan pengiriman dan pengembalian dana.",),
                ),
            ],
            ["Layanan pelanggan", "Manajemen tim", "Zendesk", "Keluhan", "Bahasa Inggris"],
            ["2013-2017 Universitas Negeri Jakarta, Komunikasi"],
        ),
        profile(
            "rio-support-en",
            "customer_service",
            "mid",
            LANG_EN,
            "Rio Ferdinand",
            "Surabaya",
            "Technical Support Specialist",
            "Technical support specialist for SaaS customers, translating bug reports "
            "into reproductions engineers can use.",
            [
                Role(
                    "Technical Support Specialist",
                    "Cloud Merdeka",
                    "2021-01",
                    "present",
                    (
                        "Handled tier-2 tickets for the API and dashboard.",
                        "Wrote the reproduction guide that cut escalations by a third.",
                    ),
                ),
                Role(
                    "Support Agent",
                    "PT Layanan Digital",
                    "2018-05",
                    "2020-12",
                    ("Resolved billing and access issues for 200 accounts.",),
                ),
            ],
            ["Technical support", "SQL", "API debugging", "Zendesk", "English"],
            ["2014-2018 Universitas Airlangga, Sistem Informasi"],
        ),
        profile(
            "siti-cs-id",
            "customer_service",
            "junior",
            LANG_ID,
            "Siti Aminah",
            "Yogyakarta",
            "Customer Service Agent",
            "Agen layanan pelanggan dengan komunikasi yang tenang dan pencatatan yang rapi.",
            [
                Role(
                    "Customer Service Agent",
                    "CV Kuliner Yogyakarta",
                    "2022-04",
                    "sekarang",
                    (
                        "Menangani pesanan dan keluhan melalui WhatsApp.",
                        "Mencatat ringkasan kasus untuk evaluasi mingguan.",
                    ),
                ),
                Role(
                    "Admin Online Shop",
                    "Toko Mandiri",
                    "2021-03",
                    "2022-03",
                    ("Mengelola pesanan marketplace dan pengiriman.",),
                ),
            ],
            ["Komunikasi", "WhatsApp Business", "Excel", "Keluhan pelanggan"],
            ["2018-2021 Universitas Ahmad Dahlan, Manajemen"],
        ),
    ]


def _marketing() -> list[Profile]:
    return [
        profile(
            "fikri-marketing-id",
            "marketing",
            "mid",
            LANG_ID,
            "Fikri Ramadhan",
            "Bandung",
            "Digital Marketing Specialist",
            "Spesialis pemasaran digital dengan pengalaman iklan berbayar dan pengukuran hasil.",
            [
                Role(
                    "Digital Marketing Specialist",
                    "PT Brand Lokal",
                    "2021-07",
                    "sekarang",
                    (
                        "Mengelola anggaran iklan bulanan dan kampanye akuisisi.",
                        "Menurunkan biaya akuisisi 18% lewat pengujian kreatif.",
                    ),
                ),
                Role(
                    "Social Media Admin",
                    "Agensi Kreatif",
                    "2019-01",
                    "2021-06",
                    ("Menjalankan kalender konten dan laporan bulanan.",),
                ),
            ],
            ["Google Ads", "Meta Ads", "Google Analytics", "Copywriting", "Excel"],
            ["2015-2019 Universitas Telkom, Ilmu Komunikasi"],
        ),
        profile(
            "clara-content-en",
            "marketing",
            "senior",
            LANG_EN,
            "Clara Wijaya",
            "Jakarta",
            "Content Marketing Lead",
            "Content lead who runs a small editorial team and ties every piece to a funnel stage.",
            [
                Role(
                    "Content Marketing Lead",
                    "Platform Andalan",
                    "2020-03",
                    "present",
                    (
                        "Built the editorial calendar and a team of three writers.",
                        "Grew organic traffic 140% in eighteen months.",
                    ),
                ),
                Role(
                    "Content Writer",
                    "PT Media Online",
                    "2016-01",
                    "2020-02",
                    ("Wrote explainers and interviews for a business audience.",),
                ),
            ],
            ["Content strategy", "SEO", "Editorial", "Analytics", "English", "Bahasa Indonesia"],
            ["2012-2016 Universitas Pelita Harapan, Ilmu Komunikasi"],
        ),
        profile(
            "joko-seo-id",
            "marketing",
            "mid",
            LANG_ID,
            "Joko Prasetyo",
            "Surabaya",
            "SEO Specialist",
            "Spesialis SEO teknis dan konten, terbiasa bekerja dengan tim produk.",
            [
                Role(
                    "SEO Specialist",
                    "Toko Pintar",
                    "2021-02",
                    "sekarang",
                    (
                        "Mengoptimalkan struktur kategori dan kecepatan halaman.",
                        "Menaikkan lalu lintas organik 60% dalam satu tahun.",
                    ),
                ),
                Role(
                    "SEO Analyst",
                    "Agensi Digital",
                    "2018-08",
                    "2021-01",
                    ("Melakukan riset kata kunci dan audit teknis situs klien.",),
                ),
            ],
            ["SEO", "Google Search Console", "Analytics", "Content", "HTML"],
            ["2014-2018 Universitas Brawijaya, Ilmu Komunikasi"],
        ),
    ]


def _regulated() -> list[Profile]:
    return [
        profile(
            "maya-legal-id",
            "legal",
            "senior",
            LANG_ID,
            "Maya Sari",
            "Jakarta",
            "Legal Counsel",
            "Legal counsel dengan pengalaman kontrak komersial, ketenagakerjaan, dan "
            "kepatuhan perusahaan.",
            [
                Role(
                    "Legal Counsel",
                    "PT Grup Niaga",
                    "2019-09",
                    "sekarang",
                    (
                        "Meninjau kontrak komersial dan perjanjian kerja sama.",
                        "Menangani perkara ketenagakerjaan bersama konsultan eksternal.",
                    ),
                ),
                Role(
                    "Legal Officer",
                    "CV Hukum Mandiri",
                    "2015-02",
                    "2019-08",
                    ("Menyiapkan dokumen perusahaan dan perizinan usaha.",),
                ),
            ],
            ["Hukum kontrak", "Hukum ketenagakerjaan", "Kepatuhan", "Perizinan"],
            ["2010-2014 Universitas Indonesia, Hukum"],
        ),
        profile(
            "andreas-compliance-en",
            "legal",
            "mid",
            LANG_EN,
            "Andreas Tanaya",
            "Jakarta",
            "Compliance Officer",
            "Compliance officer for a payments company: KYC reviews, AML monitoring "
            "and the regulator's questions.",
            [
                Role(
                    "Compliance Officer",
                    "Dompet Digital",
                    "2021-01",
                    "present",
                    (
                        "Ran KYC onboarding reviews and periodic refreshes.",
                        "Prepared AML monitoring reports for the regulator.",
                    ),
                ),
                Role(
                    "Risk Analyst",
                    "PT Pembayaran",
                    "2018-04",
                    "2020-12",
                    ("Investigated suspicious transactions and drafted case files.",),
                ),
            ],
            ["KYC", "AML", "Regulatory reporting", "Risk assessment", "Excel"],
            ["2014-2018 Universitas Katolik Indonesia Atma Jaya, Hukum"],
        ),
        profile(
            "ratna-clinic-id",
            "healthcare",
            "mid",
            LANG_ID,
            "Ratna Sari",
            "Jakarta",
            "Clinic Administrator",
            "Administrator klinik dengan pengalaman penjadwalan pasien, klaim BPJS, dan "
            "koordinasi tenaga medis.",
            [
                Role(
                    "Clinic Administrator",
                    "Klinik Sehat Bersama",
                    "2020-06",
                    "sekarang",
                    (
                        "Mengelola jadwal dokter dan pendaftaran pasien.",
                        "Menyiapkan klaim BPJS dan rekonsiliasi kunjungan.",
                    ),
                ),
                Role(
                    "Front Office",
                    "Klinik Keluarga",
                    "2017-03",
                    "2020-05",
                    ("Melayani pendaftaran dan administrasi rekam medis.",),
                ),
            ],
            ["Administrasi klinik", "Klaim BPJS", "Penjadwalan", "Rekam medis"],
            ["2013-2017 Universitas Respati Indonesia, Administrasi Rumah Sakit"],
        ),
        profile(
            "steven-hospital-en",
            "healthcare",
            "senior",
            LANG_EN,
            "Steven Halim",
            "Surabaya",
            "Hospital Operations Manager",
            "Hospital operations manager with experience across outpatient scheduling, "
            "claims and staffing.",
            [
                Role(
                    "Operations Manager",
                    "Rumah Sakit Sejahtera",
                    "2018-02",
                    "present",
                    (
                        "Ran outpatient operations across 14 clinics.",
                        "Reduced patient wait time by 25% with scheduling changes.",
                    ),
                ),
                Role(
                    "Administration Supervisor",
                    "Rumah Sakit Umum",
                    "2012-07",
                    "2018-01",
                    ("Supervised registration and medical records staff.",),
                ),
            ],
            ["Hospital operations", "Scheduling", "Claims", "Staffing", "Budgeting"],
            ["2008-2012 Universitas Airlangga, Administrasi Rumah Sakit"],
        ),
        profile(
            "dian-trainer-id",
            "education",
            "mid",
            LANG_ID,
            "Dian Saputri",
            "Yogyakarta",
            "Corporate Trainer",
            "Trainer korporat dengan pengalaman merancang materi dan memfasilitasi "
            "pelatihan komunikasi.",
            [
                Role(
                    "Corporate Trainer",
                    "PT Talenta Karya",
                    "2020-02",
                    "sekarang",
                    (
                        "Merancang dan memfasilitasi pelatihan komunikasi untuk 300 peserta.",
                        "Mengukur hasil pelatihan dengan survei sebelum dan sesudah.",
                    ),
                ),
                Role(
                    "Pengajar Bahasa Inggris",
                    "Lembaga Bahasa",
                    "2016-08",
                    "2020-01",
                    ("Mengajar kelas dewasa dan menyusun kurikulum.",),
                ),
            ],
            ["Desain pelatihan", "Fasilitasi", "Komunikasi", "Bahasa Inggris"],
            ["2012-2016 Universitas Negeri Yogyakarta, Pendidikan Bahasa Inggris"],
        ),
        profile(
            "grace-teacher-en",
            "education",
            "junior",
            LANG_EN,
            "Grace Naomi",
            "Jakarta",
            "Primary School Teacher",
            "Primary school teacher who plans lessons carefully and communicates with "
            "parents without jargon.",
            [
                Role(
                    "Primary School Teacher",
                    "Sekolah Pelita",
                    "2021-07",
                    "present",
                    (
                        "Taught grade 4 and led the reading programme.",
                        "Ran parent-teacher conferences and progress reports.",
                    ),
                ),
                Role(
                    "Teaching Assistant",
                    "Sekolah Harapan",
                    "2020-01",
                    "2021-06",
                    ("Supported lesson delivery and classroom management.",),
                ),
            ],
            ["Lesson planning", "Classroom management", "Assessment", "English"],
            ["2016-2020 Universitas Pelita Harapan, Pendidikan Guru Sekolah Dasar"],
        ),
    ]


def catalogue() -> list[Profile]:
    """All 50 profiles: 18 engineering and 32 across nine other families."""
    profiles = [*_engineering(), *_finance(), *_people_ops(), *_sales()]
    profiles.extend([*_operations(), *_service(), *_marketing(), *_regulated()])
    return profiles


PROFILES: tuple[Profile, ...] = tuple(catalogue())


def _period(role: Role) -> str:
    return f"{role.start} - {role.end}"


def render_markdown(profile: Profile) -> str:
    """The résumé as the extraction agent reads it."""
    ind = profile.language == LANG_ID
    lines = [f"# {profile.name}", f"{profile.headline}. {profile.city} | {profile.email}", ""]
    lines.append("## Ringkasan" if ind else "## Summary")
    lines.append(profile.summary)
    lines.append("")
    lines.append("## Pengalaman" if ind else "## Experience")
    for role in profile.roles:
        lines.append(f"- {_period(role)}: {role.title}, {role.company}")
        for highlight in role.highlights:
            lines.append(f"  - {highlight}")
    lines.extend(["", "## Keahlian" if ind else "## Skills"])
    lines.append(", ".join(profile.skills))
    lines.extend(["", "## Pendidikan" if ind else "## Education"])
    for entry in profile.education:
        lines.append(f"- {entry}")
    if profile.certifications:
        lines.extend(["", "## Sertifikasi" if ind else "## Certifications"])
        for entry in profile.certifications:
            lines.append(f"- {entry}")
    return "\n".join(lines).strip() + "\n"


def render_json(profile: Profile) -> str:
    """The structured-import variant an ATS export would produce."""
    return json.dumps(
        {
            "name": profile.name,
            "headline": profile.headline,
            "city": profile.city,
            "email": profile.email,
            "summary": profile.summary,
            "experience": [
                {
                    "title": role.title,
                    "company": role.company,
                    "start": role.start,
                    "end": role.end,
                    "highlights": list(role.highlights),
                }
                for role in profile.roles
            ],
            "skills": list(profile.skills),
            "education": list(profile.education),
            "certifications": list(profile.certifications),
        },
        ensure_ascii=False,
        indent=2,
    )


# --- a minimal deterministic PDF writer ---------------------------------------

_PAGE_WIDTH = 595
_PAGE_HEIGHT = 842
_MARGIN = 45
_FONT_SIZE = 9
_LEADING = 11
_MAX_CHARS = 92


def _wrap(text: str) -> list[str]:
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > _MAX_CHARS and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _pages(lines: list[str]) -> list[str]:
    usable = (_PAGE_HEIGHT - 2 * _MARGIN) // _LEADING
    return [
        "\n".join(f"({_escape(line)}) Tj T*" for line in lines[start : start + usable])
        for start in range(0, max(len(lines), 1), usable)
    ]


def _assemble(page_streams: list[str]) -> bytes:
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{4 + index * 2} 0 R" for index in range(len(page_streams)))
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_streams)} >>".encode("latin-1")
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, stream in enumerate(page_streams):
        content_id = 4 + index * 2 + 1
        page = (
            "<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        objects.append(page.encode("latin-1"))
        body = (
            f"BT /F1 {_FONT_SIZE} Tf {_MARGIN} {_PAGE_HEIGHT - _MARGIN} Td "
            f"{_LEADING} TL\n{stream}\nET"
        )
        data = body.encode("latin-1")
        objects.append(
            b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, blob in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + blob + b"\nendobj\n"
    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n").encode()
    return bytes(out)


def render_pdf(profile: Profile) -> bytes:
    """A real PDF of the rendered résumé.

    Hand-written because the dependency set has a PDF *reader* (pypdf) and no
    writer; a binary fixture nobody can regenerate would be worse than twenty
    lines of PDF plumbing.
    """
    lines: list[str] = []
    for raw in render_markdown(profile).splitlines():
        lines.extend(_wrap(raw.strip()))
    return _assemble(_pages(lines))


def render_blank_pdf() -> bytes:
    """A PDF with no text layer — the "scanned document" case.

    The extractor must return an empty string rather than raising or inventing
    text; the pipeline then treats the submission as unreadable.
    """
    return _assemble([""])
