import type { Metadata } from 'next'
import Link from 'next/link'

export const metadata: Metadata = {
  title: 'An open-source, self-hosted alternative to per-seat ATS software',
  description:
    'HRAgents is a self-hosted, Apache-2.0 recruiting and HR platform: deterministic candidate scoring, human approvals, an audit chain, and no per-seat pricing or data leaving your host.',
  alternates: { canonical: '/open-source-ats-alternative/' },
}

const GITHUB = 'https://github.com/davinakmalyasha/HRAgents'
const DOCS = 'https://davinakmalyasha.github.io/HRAgents/latest/'

export default function AtsAlternative() {
  return (
    <>
      <section className="hero">
        <div className="container">
          <p className="eyebrow">Open source · self-hosted</p>
          <h1>An ATS you can audit, not just rent.</h1>
          <p className="lede">
            Most applicant tracking systems charge per seat and keep the
            decision inside a black box. HRAgents is the opposite: Apache-2.0,
            running on your own host, with a deterministic scorer whose every
            point cites evidence and a human deciding every consequential
            outcome.
          </p>
          <div className="actions">
            <a className="button primary" href={GITHUB}>
              View the source
            </a>
            <a className="button" href={DOCS}>
              Architecture
            </a>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>What is different</h2>
          <div className="grid">
            <article className="card">
              <h3>The score is inspectable</h3>
              <p>
                Four documented dimensions, each with the references that
                produced it. Run it twice and you get the same number; a
                dimension with no evidence contributes zero.
              </p>
            </article>
            <article className="card">
              <h3>The rules are code</h3>
              <p>
                Auto-scheduling requires a high score, low variance across
                independent extractions, no anomaly flags and evidence for every
                dimension. Everything else goes to a person.
              </p>
            </article>
            <article className="card">
              <h3>The record survives</h3>
              <p>
                Every transition is written to a hash-chained audit log.
                Evaluations persist the rubric family and digest that scored
                them, so an old decision can be reconstructed.
              </p>
            </article>
            <article className="card">
              <h3>No per-seat meter</h3>
              <p>
                Self-hosted under Apache-2.0. You pay for your own compute and,
                if you choose a hosted model, your own provider — not a seat for
                every interviewer.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>What it is not</h2>
          <p className="section-lede">
            Honesty is cheaper than a disappointed trial.
          </p>
          <table>
            <tbody>
              <tr>
                <td>Not a sourcing database</td>
                <td>
                  It evaluates and runs the pipeline for the candidates you
                  bring; there is no scraped talent pool.
                </td>
              </tr>
              <tr>
                <td>Not a job-board integration suite</td>
                <td>
                  Inbound applications are an API, a CSV import and a document
                  upload today. An MCP layer and connector templates ship; a
                  direct vendor connector is not built — you point it at your own
                  gateway.
                </td>
              </tr>
              <tr>
                <td>Not a hiring decision</td>
                <td>
                  The system extracts, scores and drafts. A named person
                  decides, and the record says so.
                </td>
              </tr>
            </tbody>
          </table>
          <p className="section-lede" style={{ marginTop: '1.5rem' }}>
            Curious how the evidence and automation bounds actually work?{' '}
            <Link href="/payroll-preparation/">
              The same discipline applies to payroll
            </Link>
            .
          </p>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>Try the real thing</h2>
          <p className="section-lede">
            The quickstart runs the API, worker, scheduler and messaging bridge
            with the offline model and a local mail server. No keys, no network.
          </p>
          <div className="actions">
            <a className="button primary" href={`${DOCS}quickstart/`}>
              Read the quickstart
            </a>
            <a className="button" href={GITHUB}>
              GitHub
            </a>
          </div>
        </div>
      </section>
    </>
  )
}
