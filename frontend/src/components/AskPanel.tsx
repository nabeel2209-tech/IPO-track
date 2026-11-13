import { useState } from "react";
import { api } from "../api";
import type { AskAnswer } from "../types";

const EXAMPLES = [
  "Which 5 mainboard IPOs have done best since listing?",
  "If I got one retail lot in every SME IPO this year, how much would I have made?",
  "What would a big HNI application in Jio Platforms be worth today?",
  "How many IPOs listed in September are below their issue price?",
];

export default function AskPanel() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(q: string) {
    if (!q.trim() || busy) return;
    setQuestion(q);
    setBusy(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await api.ask(q.trim()));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ask">
      <div className="hero">
        <h1>Ask about IPO performance</h1>
        <p>
          Questions are answered by Claude using the same data as the rest of the site. It can only run the four lookups listed under each answer,
          so every number comes from the database, not from memory.
        </p>
      </div>

      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
      >
        <textarea value={question} maxLength={300} rows={3} placeholder="e.g. Which SME IPOs doubled after listing?" onChange={(e) => setQuestion(e.target.value)} />
        <div className="ask-actions">
          <span className="muted small">{question.length}/300</span>
          <button className="primary" disabled={busy || !question.trim()}>
            {busy ? "Thinking…" : "Ask"}
          </button>
        </div>
      </form>

      <div className="chips">
        {EXAMPLES.map((q) => (
          <button key={q} className="chip" onClick={() => submit(q)} disabled={busy}>
            {q}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {answer && (
        <div className="card">
          <p className="answer">{answer.answer}</p>
          {answer.tool_calls.length > 0 && (
            <details>
              <summary>How this was answered ({answer.tool_calls.length} lookup{answer.tool_calls.length > 1 ? "s" : ""})</summary>
              <ul className="calls">
                {answer.tool_calls.map((c, i) => (
                  <li key={i}>
                    <code>{c.name}</code> <code className="muted">{JSON.stringify(c.input)}</code>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
