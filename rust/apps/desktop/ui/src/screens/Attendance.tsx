import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { businessToday, command } from "../api";
import type { Employee } from "../types";
import { ErrorBox } from "../components/ui";

interface Shift {
  id: string;
  name: string;
  start_minute: number;
  end_minute: number;
  grace_minutes: number;
  workdays_mask: number;
}

interface AttendanceSummary {
  employee_id: string;
  year: number;
  month: number;
  workdays: number;
  present_days: number;
  absent_days: number;
  late_minutes: number;
  overtime_minutes: number;
  worked_minutes: number;
}

function minutes(input: string): number {
  const [h, m] = input.split(":").map(Number);
  return h * 60 + m;
}

export function Attendance() {
  const employees = useQuery({ queryKey: ["employees"], queryFn: () => command<Employee[]>("list_employees") });
  const shifts = useQuery({ queryKey: ["shifts"], queryFn: () => command<Shift[]>("list_shifts") });
  const [employeeId, setEmployeeId] = useState("");
  const [date, setDate] = useState(businessToday());
  const [inTime, setInTime] = useState("08:00");
  const [outTime, setOutTime] = useState("17:00");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const summary = useQuery({
    queryKey: ["attendance-summary", employeeId],
    queryFn: () =>
      command<AttendanceSummary>("attendance_summary", {
        employee_id: employeeId,
        shift_id: shifts.data?.[0]?.id ?? null,
        year: Number(date.slice(0, 4)),
        month: Number(date.slice(5, 7)),
      }),
    enabled: Boolean(employeeId && shifts.data?.length),
  });

  async function save() {
    setError(null);
    setSaved(false);
    try {
      await command("record_checkin", {
        employee_id: employeeId,
        date,
        in_minute: minutes(inTime),
        out_minute: minutes(outTime),
        source: "manual",
        note: null,
      });
      setSaved(true);
      await summary.refetch();
    } catch (caught) {
      setError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Attendance</h1>
          <p>Shifts, daily check-ins, and the monthly summary that feeds overtime.</p>
        </div>
      </div>
      <div className="grid two-col">
        <section className="card card-pad">
          <h2><Clock size={15} /> Record check-in</h2>
          <label className="small">Employee
            <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
              <option value="">Select…</option>
              {(employees.data ?? []).map((e) => (
                <option key={e.id} value={e.id}>{e.full_name} ({e.employee_no})</option>
              ))}
            </select>
          </label>
          <label className="small">Date <input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
          <div className="row">
            <label className="small">In <input type="time" value={inTime} onChange={(e) => setInTime(e.target.value)} /></label>
            <label className="small">Out <input type="time" value={outTime} onChange={(e) => setOutTime(e.target.value)} /></label>
          </div>
          <div className="small faint">Shifts: {(shifts.data ?? []).map((s) => s.name).join(", ") || "none yet — create one in Settings"}</div>
          {error ? <ErrorBox>{error}</ErrorBox> : null}
          {saved ? <div className="pill ok">Saved</div> : null}
          <button className="btn primary" onClick={save} disabled={!employeeId}>Save check-in</button>
        </section>
        <section className="card card-pad">
          <h2>Monthly summary</h2>
          {summary.data ? (
            <ul className="small">
              <li>Workdays: {summary.data.workdays}</li>
              <li>Present: {summary.data.present_days}</li>
              <li>Absent: {summary.data.absent_days}</li>
              <li>Late: {summary.data.late_minutes} min</li>
              <li>Overtime: {summary.data.overtime_minutes} min</li>
            </ul>
          ) : (
            <div className="small faint">Pick an employee to see this month.</div>
          )}
        </section>
      </div>
    </>
  );
}
