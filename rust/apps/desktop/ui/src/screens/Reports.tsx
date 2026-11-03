import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { command, formatIdr } from "../api";

interface CompanyReport {
  headcount: { org_unit: string; active: number }[];
  total_active: number;
  payroll_cost: { year: number; month: number; employees: number; net_sen: number }[];
  leave_recap: { employee_id: string; employee_no: string; full_name: string; approved: number; pending: number }[];
  hiring_funnel: { job_id: string; title: string; applied: number; interviewed: number; offered: number; hired: number }[];
}

export function Reports() {
  const report = useQuery({ queryKey: ["company-report"], queryFn: () => command<CompanyReport>("company_report") });
  const org = useQuery({ queryKey: ["org-tree"], queryFn: () => command<[string, string, string][]>("org_tree") });
  const data = report.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <p>Headcount, payroll cost, leave, and hiring — read-only, same data HR already sees.</p>
        </div>
        <div className="page-actions"><span className="pill"><BarChart3 size={11} /> read-only</span></div>
      </div>
      {!data ? (
        <div className="empty">Loading…</div>
      ) : (
        <div className="grid two-col">
          <section className="card card-pad">
            <h2>Headcount ({data.total_active})</h2>
            <ul className="small">
              {data.headcount.map((row) => (
                <li key={row.org_unit}>{row.org_unit}: {row.active}</li>
              ))}
            </ul>
            <h2>Org</h2>
            <ul className="small">
              {(org.data ?? []).slice(0, 50).map(([no, name, unit]) => (
                <li key={no}>{name} — {unit} ({no})</li>
              ))}
            </ul>
          </section>
          <section className="card card-pad">
            <h2>Payroll cost</h2>
            <ul className="small">
              {data.payroll_cost.map((row, i) => (
                <li key={i}>{row.employees} people · {formatIdr(row.net_sen)}</li>
              ))}
              {data.payroll_cost.length === 0 ? <li className="faint">No approved runs yet.</li> : null}
            </ul>
            <h2>Hiring funnel</h2>
            <ul className="small">
              {data.hiring_funnel.map((row) => (
                <li key={row.job_id}>{row.title}: {row.applied} applied · {row.interviewed} interviewed · {row.offered} offered · {row.hired} hired</li>
              ))}
            </ul>
            <h2>Leave</h2>
            <ul className="small">
              {data.leave_recap.map((row) => (
                <li key={row.employee_id}>{row.full_name}: {row.approved} approved · {row.pending} pending</li>
              ))}
              {data.leave_recap.length === 0 ? <li className="faint">No leave yet.</li> : null}
            </ul>
          </section>
        </div>
      )}
    </>
  );
}
