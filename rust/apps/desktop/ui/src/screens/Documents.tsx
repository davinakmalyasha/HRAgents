import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Eye, FileText, Plus, ShieldCheck, Upload } from "lucide-react";
import { command, formatDateTime } from "../api";
import type { Document, DocumentBytes, DocumentOwnerType, DocumentRequest } from "../types";
import { ErrorBox, Field, StatusPill } from "../components/ui";

function errorMessage(caught: unknown): string {
  return typeof caught === "object" && caught && "message" in caught
    ? String((caught as { message: unknown }).message)
    : String(caught);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function DocumentVault({
  ownerType,
  ownerId,
  ownerLabel,
  onError,
}: {
  ownerType: DocumentOwnerType;
  ownerId: string;
  ownerLabel: string;
  onError: (error: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<DocumentBytes | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const documents = useQuery({
    queryKey: ["documents", ownerType, ownerId],
    queryFn: () =>
      command<Document[]>("list_documents", { owner_type: ownerType, owner_id: ownerId }),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["documents", ownerType, ownerId] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
    ]);
  }

  async function upload(file: File) {
    setBusy(true);
    onError(null);
    try {
      const buffer = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      const chunk = 8192;
      for (let i = 0; i < buffer.length; i += chunk) {
        binary += String.fromCharCode(...buffer.slice(i, i + chunk));
      }
      await command<Document>("upload_document", {
        owner_type: ownerType,
        owner_id: ownerId,
        filename: file.name,
        mime_type: file.type || "application/octet-stream",
        base64: btoa(binary),
      });
      await refresh();
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function openPreview(document: Document) {
    setBusy(true);
    onError(null);
    try {
      const bytes = await command<DocumentBytes>("read_document", {
        document_id: document.id,
      });
      setPreview(bytes);
      setPreviewOpen(true);
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function verify(document: Document) {
    setBusy(true);
    onError(null);
    try {
      await command<Document>("verify_document", { document_id: document.id });
      await refresh();
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const list = documents.data ?? [];

  return (
    <div className="grid" style={{ gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div style={{ fontWeight: 620 }}>
          Documents · {ownerLabel}{" "}
          <span className="pill">{list.length}</span>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <input
            ref={fileRef}
            type="file"
            style={{ display: "none" }}
            aria-label="Choose a file to upload"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
          <button className="btn sm" disabled={busy} onClick={() => fileRef.current?.click()}>
            <Upload size={13} /> Upload
          </button>
        </div>
      </div>

      {list.length === 0 ? (
        <div className="small muted">
          No documents yet. Uploaded files are hashed (SHA-256), stored beside the database, and
          every upload, view, and verification lands on the audit chain.
        </div>
      ) : (
        <div className="card">
          {list.map((document) => (
            <div className="list-row" key={document.id}>
              <span className="icon-box">
                <FileText size={15} />
              </span>
              <div className="grow">
                <div className="title">{document.filename}</div>
                <div className="meta">
                  {document.mime_type} · {formatBytes(document.size_bytes)} · uploaded{" "}
                  {formatDateTime(document.uploaded_at)}
                  {document.expires_on ? ` · expires ${document.expires_on}` : ""}
                </div>
                <div className="mono faint" style={{ marginTop: 2 }}>
                  sha256 {document.sha256.slice(0, 20)}…
                </div>
              </div>
              <StatusPill
                tone={document.status === "verified" ? "ok" : document.status === "pending" ? "warn" : "bad"}
                label={document.status}
              />
              <span className="row" style={{ gap: 6 }}>
                <button className="btn sm" disabled={busy} onClick={() => openPreview(document)}>
                  <Eye size={13} /> Preview
                </button>
                {document.status === "pending" ? (
                  <button className="btn sm" disabled={busy} onClick={() => verify(document)}>
                    <CheckCircle2 size={13} /> Verify
                  </button>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      )}

      {previewOpen && preview ? (
        <div className="card">
          <div className="card-head">
            <FileText size={15} />
            <h3>{preview.document.filename}</h3>
            <span className="sub">
              {preview.document.mime_type} · {formatBytes(preview.size_bytes)}
            </span>
            <button className="btn ghost sm" style={{ marginLeft: "auto" }} onClick={() => setPreviewOpen(false)}>
              Close
            </button>
          </div>
          <div className="card-pad">
            <PreviewBody preview={preview} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PreviewBody({ preview }: { preview: DocumentBytes }) {
  const { document, base64 } = preview;
  if (document.mime_type.startsWith("image/")) {
    return (
      <img
        src={`data:${document.mime_type};base64,${base64}`}
        alt={document.filename}
        style={{ maxWidth: "100%", borderRadius: 8, border: "1px solid var(--line)" }}
      />
    );
  }
  if (document.mime_type.startsWith("text/") || document.mime_type === "application/json") {
    try {
      const text = atob(base64);
      return (
        <pre
          className="small"
          style={{
            whiteSpace: "pre-wrap",
            background: "var(--surface-muted)",
            border: "1px solid var(--line)",
            borderRadius: 8,
            padding: 12,
            maxHeight: 320,
            overflow: "auto",
            margin: 0,
          }}
        >
          {text.slice(0, 8000)}
        </pre>
      );
    } catch {
      return <div className="small muted">Could not decode this file as text.</div>;
    }
  }
  if (document.mime_type === "application/pdf") {
    return (
      <div className="grid" style={{ gap: 10 }}>
        <div className="notice">
          <ShieldCheck size={15} />
          <div>
            PDF preview renders inline in the packaged app. This preview shows the stored metadata
            and hash; download to open the original file.
          </div>
        </div>
        <a
          className="btn sm"
          style={{ width: "fit-content", textDecoration: "none" }}
          href={`data:${document.mime_type};base64,${base64}`}
          download={document.filename}
        >
          <Download size={13} /> Download {document.filename}
        </a>
      </div>
    );
  }
  return (
    <div className="grid" style={{ gap: 10 }}>
      <div className="small muted">
        No inline preview for {document.mime_type}. The file is stored safely; download it to open
        with the system viewer.
      </div>
      <a
        className="btn sm"
        style={{ width: "fit-content", textDecoration: "none" }}
        href={`data:${document.mime_type};base64,${base64}`}
        download={document.filename}
      >
        <Download size={13} /> Download {document.filename}
      </a>
    </div>
  );
}

export function DocumentRequests({
  employeeId,
  employeeName,
  onError,
}: {
  employeeId: string;
  employeeName: string;
  onError: (error: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [documentType, setDocumentType] = useState("KTP");
  const [dueOn, setDueOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const requests = useQuery({
    queryKey: ["document-requests", employeeId],
    queryFn: () =>
      command<DocumentRequest[]>("list_document_requests", { employee_id: employeeId }),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["document-requests", employeeId] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
    ]);
  }

  function fail(message: string) {
    setLocalError(message);
    onError(message);
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setLocalError(null);
    onError(null);
    try {
      await command<DocumentRequest>("create_document_request", {
        employee_id: employeeId,
        document_type: documentType,
        due_on: dueOn || null,
      });
      await refresh();
    } catch (caught) {
      fail(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function verify(request: DocumentRequest) {
    setBusy(true);
    setLocalError(null);
    onError(null);
    try {
      await command<DocumentRequest>("verify_document_request", { request_id: request.id });
      await refresh();
    } catch (caught) {
      fail(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const list = requests.data ?? [];

  return (
    <div className="grid" style={{ gap: 12, marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div style={{ fontWeight: 620 }}>
          Document requests · {employeeName} <span className="pill">{list.length}</span>
        </div>
      </div>
      <form className="form-grid" onSubmit={create}>
        <Field label="Document type">
          <select value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
            <option>KTP</option>
            <option>NPWP</option>
            <option>BPJS card</option>
            <option>Diploma</option>
            <option>Contract</option>
            <option>Medical certificate</option>
          </select>
        </Field>
        <Field label="Due date (optional)">
          <input type="date" value={dueOn} onChange={(event) => setDueOn(event.target.value)} />
        </Field>
        <div className="span-2">
          <button className="btn sm" type="submit" disabled={busy || !documentType}>
            <Plus size={13} /> Request document
          </button>
        </div>
        {localError ? (
          <div className="span-2">
            <ErrorBox>{localError}</ErrorBox>
          </div>
        ) : null}
      </form>
      {list.length === 0 ? (
        <div className="small muted">
          No open requests. Requested documents chase the employee; uploaded ones appear above for
          verification.
        </div>
      ) : (
        <div className="card">
          {list.map((request) => (
            <div className="list-row" key={request.id}>
              <span className="icon-box">
                <FileText size={15} />
              </span>
              <div className="grow">
                <div className="title">{request.document_type}</div>
                <div className="meta">
                  requested {formatDateTime(request.requested_at)}
                  {request.due_on ? ` · due ${request.due_on}` : ""}
                  {request.note ? ` · ${request.note}` : ""}
                </div>
              </div>
              <StatusPill
                tone={
                  request.status === "verified"
                    ? "ok"
                    : request.status === "requested" || request.status === "uploaded"
                      ? "warn"
                      : "bad"
                }
                label={request.status}
              />
              {request.status === "uploaded" ? (
                <button className="btn sm" disabled={busy} onClick={() => verify(request)}>
                  <CheckCircle2 size={13} /> Verify
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
