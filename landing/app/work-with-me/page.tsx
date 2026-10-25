import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Work with the author',
  description:
    'Freelance integration for HRAgents: installation, WhatsApp and calendar wiring, provider configuration, compliance setup, staff training and handover.',
  alternates: { canonical: '/work-with-me/' },
}

const GITHUB = 'https://github.com/davinakmalyasha/HRAgents'

export default function WorkWithMe() {
  return (
    <>
      <section className="hero">
        <div className="container">
          <p className="eyebrow">Freelance integration</p>
          <h1>The software is free. The hand-holding is the service.</h1>
          <p className="lede">
            HRAgents is built to be self-hosted, but &ldquo;self-hosted&rdquo;
            still means Docker, a domain, provider keys and a first payroll
            review. If you want it running without doing that work yourself, the
            author takes on a small number of integration engagements.
          </p>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>What an engagement covers</h2>
          <div className="grid">
            <article className="card">
              <h3>Installation and hardening</h3>
              <p>
                Compose stack on your server or laptop, Postgres/RLS verified,
                backups and the restore drill, a TLS reverse proxy, and the
                operator keys bound per person.
              </p>
            </article>
            <article className="card">
              <h3>Provider wiring</h3>
              <p>
                A model you are allowed to use (local Ollama or your own API),
                your mailbox, optional WhatsApp manual links and a calendar path.
                Every choice is recorded on the provider page.
              </p>
            </article>
            <article className="card">
              <h3>Compliance setup</h3>
              <p>
                Consent wording, retention periods by record type, erasure and
                breach workflows, and the statutory tables your payroll needs —
                entered and verified with you, never guessed by us.
              </p>
            </article>
            <article className="card">
              <h3>Training and handover</h3>
              <p>
                A working session for the HR team, the runbooks that matter
                (backup, upgrade, provider failure), and a walkthrough of the
                audit trail and approval queues.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>How to start</h2>
          <p className="section-lede">
            Open an issue on GitHub with the shape of your setup — team size, what
            you use today (spreadsheets, a per-seat ATS, WhatsApp), and whether
            payroll is in scope. A short call follows to scope the work. No
            retainers, no lead-generation funnel.
          </p>
          <div className="actions">
            <a className="button primary" href={`${GITHUB}/issues`}>
              Open an issue
            </a>
            <a className="button" href="https://github.com/davinakmalyasha">
              GitHub profile
            </a>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>What this is not</h2>
          <p className="section-lede">
            Not an outsourcing arrangement: the system is yours, the data stays
            on your host, and every decision stays with your people. Not legal or
            tax advice: the statutory numbers are entered and verified by your
            named human, and a payroll professional remains responsible for them.
          </p>
        </div>
      </section>
    </>
  )
}
