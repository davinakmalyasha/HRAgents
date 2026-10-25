import type { Metadata } from 'next'
import Link from 'next/link'

export const metadata: Metadata = {
  alternates: { canonical: '/' },
  description:
    'HRAgents is a self-hosted, open-source virtual HR team: deterministic candidate scoring, human approvals, onboarding, leave, payroll preparation, compliance and offboarding. Models extract; code decides; people approve.',
}

const GITHUB = 'https://github.com/davinakmalyasha/HRAgents'
const DOCS = 'https://davinakmalyasha.github.io/HRAgents/latest/'

export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="container">
          <p className="eyebrow">Self-hosted · open source · Apache-2.0</p>
          <h1>A virtual HR team for the HR department of one.</h1>
          <p className="lede">
            HRAgents runs hiring, onboarding, leave, payroll preparation,
            compliance, growth and offboarding in one auditable system. Language
            models read and draft. Deterministic code scores and routes. A named
            person decides everything consequential.
          </p>
          <div className="actions">
            <Link className="button primary" href="/open-source-ats-alternative/">
              How hiring works
            </Link>
            <a className="button" href={DOCS}>
              Read the docs
            </a>
            <a className="button" href={GITHUB}>
              GitHub
            </a>
          </div>
          <ul className="facts">
            <li>No cloud keys required</li>
            <li>Bring your own model</li>
            <li>Tamper-evident audit chain</li>
            <li>Bahasa Indonesia and English</li>
          </ul>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>The whole employee lifecycle, not just the ATS</h2>
          <p className="section-lede">
            Nine workspaces share one record. A decision made in hiring is the
            same employee the onboarding checklist, the leave balance and the
            offboarding clearance later refer to.
          </p>
          <div className="grid">
            <article className="card">
              <h3>Hiring</h3>
              <p>
                Candidates are scored on four documented dimensions with the
                evidence behind every point. Automation is bounded in code; a
                rejection above the merit floor needs a named human and a reason.
              </p>
            </article>
            <article className="card">
              <h3>People operations</h3>
              <p>
                Onboarding plans, contracts and expiry reminders, a document
                vault, leave balances and approvals, growth cycles and
                offboarding with asset clearance.
              </p>
            </article>
            <article className="card">
              <h3>Payroll preparation</h3>
              <p>
                Statutory tables are operator-entered and verified with a source;
                payroll refuses to compute otherwise. Runs are reviewed and
                exported — the system never moves money.
              </p>
            </article>
            <article className="card">
              <h3>Compliance</h3>
              <p>
                Consent, retention, erasures and breaches, a compliance calendar,
                and a hash-chained audit trail that can be verified on a schedule.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>A look inside</h2>
          <p className="section-lede">
            The demo dataset, seeded through the real services: the
            attention-first home, the shared approvals queue, people and records,
            and the operations page.
          </p>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="screenshot"
            src="/tour.gif"
            alt="Four screens from the HRAgents demo: home, approvals, people and records, operations"
            width={1000}
            height={560}
          />
        </div>
      </section>

      <section>
        <div className="container">
          <h2>How a decision is made</h2>
          <p className="section-lede">
            The split is the product. An agent can be wrong in a way a person
            can see; a score cannot. So the model never produces the number that
            gates a person.
          </p>
          <ol className="steps">
            <li>
              <h3>Extract</h3>
              <p>
                Agents turn a CV and portfolio into a typed profile, with a
                reference for every claim they keep. Suspected prompt injection is
                redacted and recorded.
              </p>
            </li>
            <li>
              <h3>Score and route</h3>
              <p>
                A deterministic scorer reads the evidence. Auto-scheduling needs a
                high score, low run-to-run variance, no anomalies and evidence for
                every dimension. Unevidenced dimensions score zero.
              </p>
            </li>
            <li>
              <h3>Decide</h3>
              <p>
                A person decides, with the breakdown and evidence in front of
                them. The decision, the reason and the actor go to the audit
                chain. Overrides are append-only.
              </p>
            </li>
          </ol>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>What it deliberately does not do</h2>
          <p className="section-lede">
            A shorter list than the feature list, and the reason the feature list
            can be trusted.
          </p>
          <table>
            <thead>
              <tr>
                <th>Not done</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Execute payments</td>
                <td>Payroll is prepare, verify and export; the bank file is a human step.</td>
              </tr>
              <tr>
                <td>Auto-reject above the merit floor</td>
                <td>That is a named person&apos;s decision, with a reason on the record.</td>
              </tr>
              <tr>
                <td>Run shell or arbitrary commands</td>
                <td>Agents read and draft; they do not operate the machine.</td>
              </tr>
              <tr>
                <td>Hardcode statutory rates</td>
                <td>Rate tables are operator-owned, source-verified and gated.</td>
              </tr>
              <tr>
                <td>Decide who gets hired</td>
                <td>The system routes evidence and drafts; people decide.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>Run it on your own machine</h2>
          <p className="section-lede">
            Docker Desktop, no cloud account. The offline model and local mail
            server are the defaults; nothing leaves your host until you configure
            a provider.
          </p>
          <pre>
            <code>{`git clone https://github.com/davinakmalyasha/HRAgents
cd HRAgents
uv run python scripts/setup.py
docker compose up --build -d`}</code>
          </pre>
          <div className="actions">
            <a className="button primary" href={`${DOCS}quickstart/`}>
              Five-minute quickstart
            </a>
            <a className="button" href={GITHUB}>
              Source
            </a>
          </div>
        </div>
      </section>
    </>
  )
}
