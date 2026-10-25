import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Payroll preparation without payment execution',
  description:
    'Operator-verified statutory tables, immutable reviewed runs, a review packet, and named-human sign-off. HRAgents prepares payroll and refuses to guess or move money.',
  alternates: { canonical: '/payroll-preparation/' },
}

const DOCS = 'https://davinakmalyasha.github.io/HRAgents/latest/deployment/'

export default function PayrollPreparation() {
  return (
    <>
      <section className="hero">
        <div className="container">
          <p className="eyebrow">Payroll · prepare, verify, export</p>
          <h1>Payroll preparation that refuses to guess.</h1>
          <p className="lede">
            Payroll software tends to hide two things: where the rates came from
            and who approved the run. HRAgents ships the structure and no
            numbers. A named human enters the statutory values, records the
            source, and certifies them; only then will payroll compute.
          </p>
          <div className="actions">
            <a className="button primary" href={DOCS}>
              Deployment guide
            </a>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>Why preparation, not execution</h2>
          <p className="section-lede">
            The expensive mistakes in payroll are wrong inputs and unreviewed
            changes, not the bank transfer itself. The system concentrates on the
            first two and stops before the third.
          </p>
          <div className="grid">
            <article className="card">
              <h3>Rate tables are operator data</h3>
              <p>
                BPJS shares, PPh 21 brackets, overtime premiums and THR formulas
                arrive as empty, unverified shells. Nothing is hardcoded; a
                table nobody verified blocks the run.
              </p>
            </article>
            <article className="card">
              <h3>A reviewed run is immutable</h3>
              <p>
                Editing and recomputing stop at draft/assembling. A re-run is a
                linked successor with a reason; the reviewed run keeps its lines,
                figures and rate-table provenance.
              </p>
            </article>
            <article className="card">
              <h3>Anomalies are separated</h3>
              <p>
                Blocking anomalies and advisory ones are split so the reviewer
                knows what must be resolved before sign-off and what is context.
              </p>
            </article>
            <article className="card">
              <h3>The review packet is a review artifact</h3>
              <p>
                An XLSX packet prints the period, the lines, the rate-table ids
                and the replaced run id where applicable. It says on its face that
                it is not a payment instruction.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>The gates, in order</h2>
          <ol className="steps">
            <li>
              <h3>Inputs</h3>
              <p>
                A run names its period and kind. A stale edit cannot overwrite a
                run someone else moved on; the save answers a conflict instead.
              </p>
            </li>
            <li>
              <h3>Compute</h3>
              <p>
                Math runs against verified tables only. An unverified or expired
                table stops the run; the reason names the table.
              </p>
            </li>
            <li>
              <h3>Review</h3>
              <p>
                The reviewer reads the packet and the anomalies. Approval is a
                shared queue decision by a person who may approve payroll.
              </p>
            </li>
            <li>
              <h3>Export</h3>
              <p>
                The signed-off run exports; paying it is an outside step. The
                audit chain keeps the approval, the figures and the actor.
              </p>
            </li>
          </ol>
        </div>
      </section>

      <section>
        <div className="container">
          <h2>What it does not claim</h2>
          <p className="section-lede">
            No statutory knowledge is shipped, and no bank integration exists.
            HRAgents is not a substitute for a payroll professional or a tax
            adviser; it is the system that makes their inputs and approvals
            inspectable.
          </p>
          <div className="actions">
            <a className="button primary" href={DOCS}>
              How verification works
            </a>
          </div>
        </div>
      </section>
    </>
  )
}
