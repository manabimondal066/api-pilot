import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { FileUp, Link2, Terminal, UploadCloud } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { inputClass } from "@/lib/utils";

const MAX_BYTES = 10 * 1024 * 1024; // 10 MB

function ImportCardHeader({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-foreground">
        {icon}
      </span>
      <h2 className="font-semibold text-sm">{title}</h2>
    </div>
  );
}

export function ImportPage() {
  const navigate = useNavigate();

  // ---- File upload state --------------------------------------------------
  const [file, setFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ---- URL import state ---------------------------------------------------
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [urlBusy, setUrlBusy] = useState(false);

  // ---- cURL import state ---------------------------------------------------
  const [curlText, setCurlText] = useState("");
  const [curlSuiteName, setCurlSuiteName] = useState("");
  const [curlError, setCurlError] = useState<string | null>(null);
  const [curlBusy, setCurlBusy] = useState(false);

  const anyBusy = uploadBusy || urlBusy || curlBusy;

  // ---- Drag-and-drop handlers ---------------------------------------------

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
  }

  function onDragEnter(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragOver(true);
  }

  function onDragLeave(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragOver(false);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) {
      setFile(dropped);
      setFileError(null);
    }
  }

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    if (f) {
      setFile(f);
      setFileError(null);
    }
  }

  // ---- Actions ------------------------------------------------------------

  function handleUpload() {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setFileError("File is too large. Maximum size is 10 MB.");
      return;
    }
    setUploadBusy(true);
    setFileError(null);
    api
      .importFromUpload(file)
      .then((suite) => navigate(`/suites/${suite.id}`))
      .catch((e: unknown) => {
        setFileError(e instanceof Error ? e.message : "Upload failed");
      })
      .finally(() => setUploadBusy(false));
  }

  function handleUrlImport() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setUrlBusy(true);
    setUrlError(null);
    api
      .importFromUrl(trimmed)
      .then((suite) => navigate(`/suites/${suite.id}`))
      .catch((e: unknown) => {
        setUrlError(e instanceof Error ? e.message : "Import failed");
      })
      .finally(() => setUrlBusy(false));
  }

  function handleCurlImport() {
    const trimmed = curlText.trim();
    if (!trimmed) return;
    setCurlBusy(true);
    setCurlError(null);
    api
      .importFromCurl(trimmed, curlSuiteName)
      .then((suite) => navigate(`/suites/${suite.id}`))
      .catch((e: unknown) => {
        setCurlError(e instanceof Error ? e.message : "Import failed");
      })
      .finally(() => setCurlBusy(false));
  }

  // ---- Render -------------------------------------------------------------

  return (
    <div className="max-w-4xl space-y-6 animate-fade-in">
      <div>
        <h1 className="text-page-title">Import a Spec</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Upload a Swagger / OpenAPI file, import from a URL, or paste one or
          more cURL commands.
        </p>
      </div>

      <div className="grid md:grid-cols-3 gap-5 stagger-in">
        {/* ---- File upload card ------------------------------------------ */}
        <Card className="p-5 space-y-4">
          <ImportCardHeader icon={<FileUp className="h-4 w-4" />} title="Upload file" />

          {/* Drop zone */}
          <div
            role="button"
            tabIndex={0}
            aria-label="Click or drag a file here to upload"
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            onDragOver={onDragOver}
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            className={[
              "flex flex-col items-center justify-center gap-1.5 rounded-xl",
              "border-2 border-dashed px-4 py-8 cursor-pointer",
              "transition-all duration-150 select-none text-sm",
              isDragOver
                ? "border-primary bg-primary/8 scale-[1.01]"
                : "border-border hover:border-primary/50 hover:bg-accent/40",
            ].join(" ")}
          >
            <UploadCloud className={`h-6 w-6 mb-1 ${isDragOver ? "text-primary" : "text-muted-foreground"}`} />
            {file ? (
              <>
                <span className="font-medium text-foreground truncate max-w-full px-2 text-center">
                  {file.name}
                </span>
                <span className="text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(0)} KB · click to change
                </span>
              </>
            ) : (
              <>
                <span className="text-muted-foreground">
                  Drop file here or{" "}
                  <span className="underline text-foreground">browse</span>
                </span>
                <span className="text-xs text-muted-foreground/70">
                  .json · .yaml · .yml · max 10 MB
                </span>
              </>
            )}
          </div>

          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,.yaml,.yml"
            className="hidden"
            onChange={onFileChange}
          />

          <Button
            onClick={handleUpload}
            disabled={!file || anyBusy}
            className="w-full"
          >
            {uploadBusy ? "Uploading…" : "Upload"}
          </Button>

          {fileError && (
            <p className="text-sm text-destructive">{fileError}</p>
          )}
        </Card>

        {/* ---- URL import card ------------------------------------------- */}
        <Card className="p-5 space-y-4">
          <ImportCardHeader icon={<Link2 className="h-4 w-4" />} title="Import from URL" />

          <input
            type="url"
            placeholder="https://example.com/openapi.json"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              if (urlError) setUrlError(null);
            }}
            disabled={anyBusy}
            className={inputClass}
          />

          <Button
            onClick={handleUrlImport}
            disabled={!url.trim() || anyBusy}
            className="w-full"
          >
            {urlBusy ? "Importing…" : "Import from URL"}
          </Button>

          {urlError && (
            <p className="text-sm text-destructive">{urlError}</p>
          )}
        </Card>

        {/* ---- cURL import card -------------------------------------------- */}
        <Card className="p-5 space-y-4">
          <ImportCardHeader icon={<Terminal className="h-4 w-4" />} title="Import from cURL" />

          <textarea
            placeholder={"curl https://api.example.com/users \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"name\": \"Alice\"}'"}
            value={curlText}
            onChange={(e) => {
              setCurlText(e.target.value);
              if (curlError) setCurlError(null);
            }}
            disabled={anyBusy}
            rows={6}
            className={`${inputClass} font-mono resize-y`}
          />

          <input
            type="text"
            placeholder="Suite name (optional)"
            value={curlSuiteName}
            onChange={(e) => setCurlSuiteName(e.target.value)}
            disabled={anyBusy}
            className={inputClass}
          />

          <p className="text-xs text-muted-foreground/70">
            Paste one or more curl commands — each becomes an endpoint.
          </p>

          <Button
            onClick={handleCurlImport}
            disabled={!curlText.trim() || anyBusy}
            className="w-full"
          >
            {curlBusy ? "Importing…" : "Import from cURL"}
          </Button>

          {curlError && (
            <p className="text-sm text-destructive">{curlError}</p>
          )}
        </Card>
      </div>
    </div>
  );
}
