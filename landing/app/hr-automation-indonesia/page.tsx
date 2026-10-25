import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'HR automation for Indonesian SMEs, self-hosted',
  description:
    'Self-hosted HR automation for Indonesian SMEs: Bahasa Indonesia, Jakarta business dates, UU PDP consent and retention workflows, WhatsApp manual links, and operator-verified BPJS/PPh 21/THR tables.',
  alternates: { canonical: '/hr-automation-indonesia/' },
}

const GITHUB = 'https://github.com/davinakmalyasha/HRAgents'
const DOCS = 'https://davinakmalyasha.github.io/HRAgents/latest/'

export default function Indonesia() {
  return (
    <>
      <section className="hero">
        <div className="container">
          <p className="eyebrow">Indonesia · self-hosted</p>
          <h1>HR automation built for how Indonesian SMEs actually run.</h1>
          <p className="lede">
            One HR person, a WhatsApp-first candidate pipeline, a Jakarta
            calendar, and a data-protection law that expects consent and erasure
            to be real. HRAgents runs on your own host, in Bahasa Indonesia and
            English, and keeps the record.
          </p>
          <div className="actions">
            <a className="button primary" href={DOCS}>
              Documentation
            </a>
            <a className="button" href={GITHUB}>
              GitHub
            </a>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>Local by design</h2>
          <div className="grid">
            <article className="card">
              <h3>Business dates in WIB</h3>
              <p>
                Leave years, probation ends, contract expiry and retention clocks
                are read in <code>Asia/Jakarta</code>, configurable per
                deployment. A server in UTC no longer runs a day behind after
                midnight.
              </p>
            </article>
            <article className="card">
              <h3>Statutory tables, not guesses</h3>
              <p>
                BPJS, PPh 21, overtime and THR logic ship as empty shells. A
                named human enters the rates from the regulation and verifies
                them; payroll refuses to compute before that.
              </p>
            </article>
            <article className="card">
              <h3>UU PDP workflows</h3>
              <p>
                Consent is captured with a purpose, withdrawals need a reason,
                erasure walks a ledger, and retention sweeps report what they
                destroyed, spared and failed.
              </p>
            </article>
            <article className="card">
              <h3>WhatsApp without an API bill</h3>
              <p>
                Manual mode composes a <code>wa.me</code> link, a person sends
                it, and the dispatch is recorded. The Meta Cloud adapter is
                configuration-gated when an operator has it.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>What leaves the host</h2>
          <p className="section-lede">
            By default: nothing. The offline test model, hash embeddings, local
            document storage and a local mail server are the defaults. An
            operator who configures a hosted model or SMTP decides which provider
            sees the data; the provider page says what is in use, and credentials
            entered in the dashboard are encrypted at rest.
          </p>
          <table>
            <tbody>
              <tr>
                <td>Model</td>
                <td>Offline test model by default; Ollama, Anthropic, OpenAI-compatible or Command Code when configured.</td>
              </tr>
              <tr>
                <td>Documents</td>
                <td>PostgreSQL on your host. Optional ClamAV scanning before storage.</td>
              </tr>
              <tr>
                <td>Email</td>
                <td>Mailpit locally; SMTP/IMAP or Resend when an operator connects a mailbox.</td>
              </tr>
              <tr>
                <td>Analytics</td>
                <td>None on this site and none in the product.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>Getting started</h2>
          <p className="section-lede">
            Docker Desktop, five minutes, no cloud keys. The demo dataset seeds
            five employees, a hiring pipeline, a pending leave request and a
            payroll run through the real services.
          </p>
          <div className="actions">
            <a className="button primary" href={`${DOCS}quickstart/`}>
              Quickstart
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
