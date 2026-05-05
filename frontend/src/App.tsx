import { AlertTriangle, BrainCircuit, FlaskConical, Play, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import AgentTrace from "./components/AgentTrace";
import EvidenceBoard from "./components/EvidenceBoard";
import ReviewerPacket from "./components/ReviewerPacket";
import UploadPanel from "./components/UploadPanel";
import type { Fixture, RunResult } from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export default function App() {
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [fixtureId, setFixtureId] = useState("clean");
  const [fieldDomain, setFieldDomain] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [artifactFile, setArtifactFile] = useState<File | null>(null);
  const [scriptFile, setScriptFile] = useState<File | null>(null);
  const [reportedResult, setReportedResult] = useState("");
  const [run, setRun] = useState<RunResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/fixtures`)
      .then((response) => response.json())
      .then((payload) => setFixtures(payload.fixtures ?? []))
      .catch(() => {
        setFixtures([
          { id: "clean", label: "Clean computational paper", reported_result: 0.87 },
          { id: "suspicious", label: "Suspicious/adversarial paper", reported_result: 0.91 },
        ]);
      });
  }, []);

  const board = run?.board;
  const repro = board?.repro_checks[0];
  const headline = board?.final_packet.triage_recommendation ?? "No run yet";
  const highRiskCount = useMemo(
    () => board?.concerns.filter((concern) => concern.severity === "high").length ?? 0,
    [board],
  );

  async function analyze() {
    setLoading(true);
    setError(null);
    const form = new FormData();
    form.set("fixture_id", fixtureId);
    if (fieldDomain) form.set("field_domain", fieldDomain);
    if (file) form.set("file", file);
    if (artifactFile) form.set("artifact_file", artifactFile);
    if (scriptFile) form.set("script_file", scriptFile);
    if (reportedResult) form.set("reported_result", reportedResult);

    try {
      const response = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new Error(await response.text());
      setRun(await response.json());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="masthead">
          <img className="wordmark" src="/wordmark.svg" alt="RefereeOS" />
          <p className="eyebrow">AG2 · Daytona · Beta LLM Review Operations</p>
        </div>
        <div className="sponsor-strip" aria-label="Sponsor integration status">
          <span title="AG2 synthesizes the area-chair packet when enabled">
            <BrainCircuit size={16} /> AG2
          </span>
          <span title="Daytona runs the reproducibility sandbox">
            <FlaskConical size={16} /> Daytona
          </span>
          <span title="Beta LLM interprets the Daytona reproducibility receipt">
            <ShieldCheck size={16} /> Beta LLM
          </span>
        </div>
      </header>

      <section className="command-band">
        <UploadPanel
          fixtures={fixtures}
          fixtureId={fixtureId}
          fieldDomain={fieldDomain}
          file={file}
          artifactFile={artifactFile}
          scriptFile={scriptFile}
          reportedResult={reportedResult}
          loading={loading}
          onFixtureChange={setFixtureId}
          onFieldDomainChange={setFieldDomain}
          onFileChange={setFile}
          onArtifactFileChange={setArtifactFile}
          onScriptFileChange={setScriptFile}
          onReportedResultChange={setReportedResult}
          onAnalyze={analyze}
        />
        <div className="run-summary">
          <div>
            <p className="label">Run</p>
            <strong data-mono>{run?.run_id ?? "standby"}</strong>
          </div>
          <div>
            <p className="label">Triage</p>
            <strong>{headline}</strong>
          </div>
          <div>
            <p className="label">High Risks</p>
            <strong>{highRiskCount}</strong>
          </div>
          <div>
            <p className="label">Repro</p>
            <strong className={`status-text ${repro?.status ?? "not_run"}`}>{repro?.status ?? "not run"}</strong>
          </div>
          <button className="primary-action" onClick={analyze} disabled={loading}>
            <Play size={17} />
            {loading ? "Running" : "Run Review"}
          </button>
        </div>
      </section>

      {error && (
        <div className="error-banner">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      <section className="workspace-grid">
        <AgentTrace trace={board?.agent_trace ?? []} />
        <EvidenceBoard board={board} />
        <ReviewerPacket markdown={run?.packet ?? ""} runId={run?.run_id} />
      </section>
    </main>
  );
}
