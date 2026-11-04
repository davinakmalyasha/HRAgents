export type Surface = "today" | "hire" | "people" | "pay" | "ask" | "settings" | "attendance" | "reports";

export const SURFACES: { id: Surface; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "hire", label: "Hire" },
  { id: "people", label: "People" },
  { id: "pay", label: "Pay" },
  { id: "attendance", label: "Attendance" },
  { id: "reports", label: "Reports" },
  { id: "ask", label: "Ask" },
  { id: "settings", label: "Settings" },
];
