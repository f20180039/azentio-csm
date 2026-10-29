import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { RulePackInfo } from '../api/types';
import { useToast } from '../components/Toasts';

export function Packs() {
  const [packs, setPacks] = useState<RulePackInfo[] | null>(null);
  const toast = useToast();

  useEffect(() => {
    api.listPacks().then(setPacks).catch((e) => {
      toast.error(e);
      setPacks([]);
    });
  }, [toast]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Rule packs</h1>
          <p className="sub">
            Each case type has its own rules and weights. A case's risk score is the sum of weight × severity factor (low 0.3, medium 0.6,
            high 1.0) across its findings, capped at 1.
          </p>
        </div>
      </div>
      {packs === null && <p className="muted">Loading packs…</p>}
      <div className="packs">
        {packs?.map((p) => (
          <section key={p.caseType} className="panel pack" aria-labelledby={`pack-${p.caseType}`}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <div>
                <h2 id={`pack-${p.caseType}`}>{p.label ?? p.caseType}</h2>
                <span className="mono small muted">
                  {p.caseType}
                  {p.extractionSchema ? ` · schema ${p.extractionSchema}` : ''}
                </span>
              </div>
              {p.routing && (
                <div className="routing">
                  <span>
                    <span className="pill ok">Auto-clear</span> below <span className="num">{p.routing.autoClearBelow}</span>
                  </span>
                  <span>
                    <span className="pill bad">Escalate</span> at <span className="num">{p.routing.escalateAtOrAbove}</span> or above
                  </span>
                </div>
              )}
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Weight</th>
                    <th>Why this weight</th>
                    <th>Parameters</th>
                  </tr>
                </thead>
                <tbody>
                  {p.rules.map((r) => (
                    <tr key={r.id}>
                      <td className="mono small">{r.id}</td>
                      <td>
                        <span className="weight-bar">
                          <span className="track" aria-hidden="true">
                            <span className="fill" style={{ display: 'block', width: `${Math.min(100, r.weight * 100)}%` }} />
                          </span>
                          <span className="num">{r.weight.toFixed(2)}</span>
                        </span>
                      </td>
                      <td className="rationale">{r.rationale ?? <span className="muted">No rationale recorded</span>}</td>
                      <td className="mono small">
                        {r.params && Object.keys(r.params).length
                          ? Object.entries(r.params).map(([k, v]) => (
                              <div key={k}>
                                {k}: {String(v)}
                              </div>
                            ))
                          : <span className="muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
