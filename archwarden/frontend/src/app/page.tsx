'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

// ── Types ──────────────────────────────────────────────────────────────────

interface GraphStats {
  node_count: number;
  edge_count: number;
  labels: { label: string; count: number }[];
  services: { name: string; language: string }[];
}

interface GraphData {
  nodes: { id: string; label: string; display: string }[];
  edges: { source: string; target: string; rel: string }[];
}

interface Violation {
  principle_id: string;
  severity: string;
  statement: string;
  fix_hint: string;
  [key: string]: string | number | boolean | undefined;
}

interface AuditResult {
  total_violations: number;
  violations: Violation[];
}

interface Health {
  status: string;
  graph: string;
  engine: string;
  nodes: number;
  edges: number;
  llm_available: boolean;
}
interface RemediationResult {
  violation_id: string;
  patch: string;
  explanation: string;
  verification: {
    verified: boolean;
    original_violations?: number | null;
    shadow_violations?: number | null;
    new_secondary_violations?: string[];
    cycles_detected?: number | null;
    message?: string;
  };
}
// ── Label colors ───────────────────────────────────────────────────────────

const LABEL_COLORS: Record<string, string> = {
  Service: '#76e3ff',
  Symbol: '#a78bfa',
  File: '#4ade80',
  Route: '#fbbf24',
  ClientCall: '#fb923c',
  Table: '#f87171',
  Topic: '#38bdf8',
  ConfigKey: '#a3e635',
};

const getColor = (label: string) => LABEL_COLORS[label] || '#888';

// ── Sidebar ────────────────────────────────────────────────────────────────

function Sidebar({ active, onNav }: { active: string; onNav: (p: string) => void }) {
  const items = [
    { id: 'dashboard', icon: '⬡', label: 'Dashboard', desc: 'Overview' },
    { id: 'graph',     icon: '◎', label: 'Graph',     desc: 'D3 visualization' },
    { id: 'audit',    icon: '⚑', label: 'Audit',     desc: 'Violations' },
    { id: 'review',   icon: '⤳', label: 'PR Review', desc: 'Diff analysis' },
    { id: 'principles', icon: '⊛', label: 'Principles', desc: 'Nemotron mining' },
  ];

  return (
    <aside
      role="navigation"
      aria-label="Main navigation"
      style={{
        width: 228,
        background: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        padding: '0 10px',
        flexShrink: 0,
      }}
    >
      {/* Brand */}
      <div style={{ padding: '22px 10px 24px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          <div
            className="animate-spin-slow"
            style={{
              width: 36, height: 36,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 10,
              background: 'linear-gradient(135deg, rgba(94,207,255,0.15), rgba(180,158,255,0.1))',
              border: '1px solid rgba(94,207,255,0.2)',
              fontSize: 20,
            }}
            aria-hidden="true"
          >⬡</div>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 800, letterSpacing: '-0.025em' }}
                 className="grad-cyan-violet">Archwarden</div>
            <div style={{ fontSize: '0.65rem', color: 'var(--text-dim)', marginTop: 1, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              Architecture Guard
            </div>
          </div>
        </div>
      </div>

      {/* Nav links */}
      <nav style={{ flex: 1, paddingTop: 14, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {items.map(item => (
          <div
            key={item.id}
            className={`nav-item ${active === item.id ? 'active' : ''}`}
            onClick={() => onNav(item.id)}
            role="button"
            tabIndex={0}
            aria-current={active === item.id ? 'page' : undefined}
            onKeyDown={e => e.key === 'Enter' && onNav(item.id)}
          >
            <span style={{ fontSize: 15, opacity: active === item.id ? 1 : 0.6 }} aria-hidden="true">{item.icon}</span>
            <div>
              <div>{item.label}</div>
              {active !== item.id && (
                <div style={{ fontSize: '0.68rem', color: 'var(--text-dim)', marginTop: 1 }}>{item.desc}</div>
              )}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer branding */}
      <div style={{ padding: '14px 10px 32px', borderTop: '1px solid var(--border)' }}>
        <div className="section-label" style={{ marginBottom: 10 }}>Powered by</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div className="pill pill-green" style={{ fontSize: '0.68rem', justifyContent: 'center' }}>
            ⬡ NVIDIA Nemotron
          </div>
          <div className="pill pill-cyan" style={{ fontSize: '0.68rem', justifyContent: 'center' }}>
            ◎ FalkorDB OpenCypher
          </div>
        </div>
      </div>
    </aside>
  );
}

// ── Stat Card ──────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color, icon }: { label: string; value: string | number; sub?: string; color?: string; icon?: string }) {
  return (
    <div className="stat-card animate-fade-up" role="region" aria-label={`${label}: ${value}`}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="section-label">{label}</div>
        {icon && <span style={{ fontSize: 18, opacity: 0.5 }} aria-hidden="true">{icon}</span>}
      </div>
      <div style={{ fontSize: '2.1rem', fontWeight: 800, color: color || 'var(--text-primary)', lineHeight: 1, letterSpacing: '-0.03em' }}
           className="animate-count-up">
        {value}
      </div>
      {sub && <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: 8 }}>{sub}</div>}
    </div>
  );
}

// ── Violation Card ─────────────────────────────────────────────────────────

function ViolationCard({ v, index }: { v: Violation; index: number }) {
  const [open, setOpen] = useState(false);

  const [showRemediation, setShowRemediation] = useState(false);
  const [remediating, setRemediating] = useState(false);
  const [remediationError, setRemediationError] = useState('');
  const [remediation, setRemediation] = useState<RemediationResult | null>(null);
  const [filePath, setFilePath] = useState(String(v.file_path || v.file || ''));
  const [codeSnippet, setCodeSnippet] = useState(
    String(v.code_snippet || v.snippet || '')
  );

  const handleRemediate = async () => {
    setShowRemediation(true);
    setRemediating(true);
    setRemediationError('');
    setRemediation(null);

    try {
      const response = await fetch(`${API}/review/remediate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          violation_id: v.principle_id,
          principle_statement: v.statement,
          file_path: filePath,
          code_snippet: codeSnippet,
          fix_hint: v.fix_hint || '',
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : 'Remediation request failed.'
        );
      }

      setRemediation(data as RemediationResult);
    } catch (error) {
      setRemediationError(
        error instanceof Error ? error.message : 'Something went wrong.'
      );
    } finally {
      setRemediating(false);
    }
  };


  return (
    <div className="violation-card" style={{ animationDelay: `${index * 0.04}s`, cursor: 'pointer' }}
         onClick={() => setOpen(o => !o)}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{
              fontSize: '0.72rem', fontWeight: 700, padding: '2px 8px',
              borderRadius: 20, fontFamily: 'monospace'
            }} className={`badge-${v.severity}`}>{v.severity.toUpperCase()}</span>
            <span style={{ fontFamily: 'monospace', fontSize: '0.8rem', color: 'var(--accent-cyan)', fontWeight: 600 }}>
              [{v.principle_id}]
            </span>
          </div>
          <div style={{ fontSize: '0.88rem', color: 'var(--text-primary)', fontWeight: 500, lineHeight: 1.5 }}>
            {v.statement}
          </div>
        </div>
        <span style={{ color: 'var(--text-dim)', fontSize: 14, flexShrink: 0 }}>{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
            {Object.entries(v).filter(([k]) => !['principle_id', 'severity', 'statement', 'fix_hint'].includes(k))
              .map(([k, val]) => val && (
                <span key={k} style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: 6,
                  background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                  <span style={{ color: 'var(--text-dim)' }}>{k}: </span>
                  <span style={{ color: 'var(--accent-violet)' }}>{String(val)}</span>
                </span>
              ))}
          </div>
          <div style={{ fontSize: '0.8rem', padding: '10px 14px', borderRadius: 8,
            background: 'rgba(74, 222, 128, 0.06)', border: '1px solid rgba(74,222,128,0.2)' }}>
            <span style={{ color: 'var(--accent-green)', fontWeight: 600 }}>💡 Fix: </span>
            <span style={{ color: 'var(--text-muted)' }}>{v.fix_hint}</span>
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={(event) => {
              event.stopPropagation();
              handleRemediate();
            }}
            disabled={remediating}
            aria-label={remediating ? 'Generating AI patch…' : 'Auto-remediate this violation with Nemotron AI'}
            style={{ marginTop: 14 }}
          >
            {remediating ? (
              <><span style={{ display: 'inline-block', animation: 'spin-slow 1s linear infinite' }}>⟳</span> Generating patch…</>
            ) : (
              '✨ Auto-Remediate with Nemotron'
            )}
          </button>

        </div>
      )}

      {showRemediation && (
        <div
          className="modal-overlay"
          onClick={(event) => event.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-label="Nemotron AI Remediation"
        >
          <div className="modal-panel" style={{ padding: '28px 32px' }}>
            {/* Modal header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 22 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                  <span style={{ fontSize: 20 }} aria-hidden="true">✨</span>
                  <h2 style={{ fontSize: '1.15rem', fontWeight: 700, margin: 0 }}>Nemotron AI Remediation</h2>
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>
                  Violation <span style={{ fontFamily: 'JetBrains Mono, monospace', color: 'var(--accent-cyan)' }}>[{v.principle_id}]</span>
                </div>
              </div>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setShowRemediation(false)}
                aria-label="Close remediation modal"
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              >
                ✕ Close
              </button>
            </div>

            <div className="divider" style={{ margin: '0 0 20px' }} />

            <label htmlFor="rem-filepath" style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>
              File path
            </label>
            <input
              id="rem-filepath"
              className="input"
              value={filePath}
              onChange={(event) => setFilePath(event.target.value)}
              placeholder="e.g. services/orders.py"
              style={{ marginBottom: 14 }}
            />

            <label htmlFor="rem-snippet" style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>
              Code snippet
            </label>
            <textarea
              id="rem-snippet"
              className="input"
              value={codeSnippet}
              onChange={(event) => setCodeSnippet(event.target.value)}
              placeholder="Paste the relevant code here…"
              rows={5}
              style={{ marginBottom: 16, fontFamily: 'JetBrains Mono, monospace', resize: 'vertical' }}
            />

            <button
              type="button"
              className="btn btn-primary"
              onClick={handleRemediate}
              disabled={remediating || !filePath.trim() || !codeSnippet.trim()}
              aria-label={remediating ? 'Generating patch' : 'Generate remediation patch'}
            >
              {remediating ? '⟳ Generating patch…' : '⚡ Generate / Retry Patch'}
            </button>

            {remediationError && (
              <div style={{ marginTop: 14, padding: '10px 14px', borderRadius: 8,
                background: 'rgba(255,107,107,0.08)', border: '1px solid rgba(255,107,107,0.22)',
                color: 'var(--accent-red)', fontSize: '0.85rem' }}>
                ⚠ {remediationError}
              </div>
            )}

            {remediation && (
              <div style={{ marginTop: 24 }} className="animate-fade-up">
                {/* Explanation */}
                <div style={{ marginBottom: 20 }}>
                  <div className="section-label" style={{ marginBottom: 8 }}>AI Explanation</div>
                  <p style={{ color: 'var(--text-muted)', lineHeight: 1.7, fontSize: '0.9rem' }}>
                    {remediation.explanation}
                  </p>
                </div>

                {/* Patch diff */}
                <div style={{ marginBottom: 16 }}>
                  <div className="section-label" style={{ marginBottom: 8 }}>Proposed Patch</div>
                  <pre style={{
                    padding: '16px 18px',
                    borderRadius: 10,
                    background: '#050510',
                    border: '1px solid var(--border)',
                    borderLeft: '3px solid var(--accent-violet)',
                    overflowX: 'auto',
                    whiteSpace: 'pre-wrap',
                    overflowWrap: 'anywhere',
                    fontSize: '0.78rem',
                    fontFamily: 'JetBrains Mono, monospace',
                    lineHeight: 1.7,
                    maxHeight: 320,
                    overflowY: 'auto',
                  }}>
                    {remediation.patch
                      ? remediation.patch.split('\n').map((line, i) => (
                          <span
                            key={i}
                            style={{
                              display: 'block',
                              color: line.startsWith('+') && !line.startsWith('+++')
                                ? 'var(--accent-green)'
                                : line.startsWith('-') && !line.startsWith('---')
                                  ? 'var(--accent-red)'
                                  : 'var(--text-dim)',
                              background: line.startsWith('+') && !line.startsWith('+++')
                                ? 'rgba(61,224,122,0.04)'
                                : line.startsWith('-') && !line.startsWith('---')
                                  ? 'rgba(255,107,107,0.04)'
                                  : 'transparent',
                              paddingLeft: 4,
                            }}
                          >
                            {line || '\u00a0'}
                          </span>
                        ))
                      : <span style={{ color: 'var(--text-dim)' }}>No patch returned. Review the explanation above.</span>}
                  </pre>
                </div>

                {/* Actions */}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={!remediation.patch}
                    onClick={() => { void navigator.clipboard.writeText(remediation.patch); }}
                    aria-label="Copy patch to clipboard"
                  >
                    📋 Copy Patch
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={!remediation.patch}
                    onClick={() => {
                      const blob = new Blob([remediation.patch], { type: 'text/x-diff' });
                      const url = URL.createObjectURL(blob);
                      const link = document.createElement('a');
                      link.href = url;
                      link.download = 'nemotron-remediation.patch';
                      link.click();
                      URL.revokeObjectURL(url);
                    }}
                    aria-label="Download .patch file"
                  >
                    ⬇ Download .patch
                  </button>
                </div>

                {/* Shadow verification banner */}
                <div style={{
                  padding: '14px 18px',
                  borderRadius: 10,
                  border: `1px solid ${remediation.verification.verified ? 'rgba(61,224,122,0.3)' : 'rgba(255,107,107,0.25)'}`,
                  background: remediation.verification.verified ? 'rgba(61,224,122,0.06)' : 'rgba(255,107,107,0.06)',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 12,
                }}>
                  <span style={{ fontSize: 22, flexShrink: 0 }}>
                    {remediation.verification.verified ? '🛡️' : '⚠️'}
                  </span>
                  <div>
                    <div style={{ fontWeight: 700, marginBottom: 4, color: remediation.verification.verified ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {remediation.verification.verified
                        ? 'Shadow Graph Verified — Architecture Compliant'
                        : 'Shadow Verification Inconclusive'}
                    </div>
                    <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>
                      {remediation.verification.message || 'The backend has not confirmed verification.'}
                    </div>
                    {remediation.verification.original_violations != null && (
                      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <span className="pill pill-red">Before: {remediation.verification.original_violations} violations</span>
                        <span className="pill pill-green">After: {remediation.verification.shadow_violations ?? 0} violations</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

    </div>
  );
}

// ── D3 Graph View ─────────────────────────────────────────────────────────

function GraphView() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [loading, setLoading] = useState(true);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [seeding, setSeeding] = useState(false);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/graph/graph-data`);
      const data: GraphData = await res.json();
      setGraphData(data);

      if (!svgRef.current) return;
      const svg = d3.select(svgRef.current);
      svg.selectAll('*').remove();

      if (!data.nodes || !data.nodes.length) return;

      const w = svgRef.current.clientWidth || 800;
      const h = svgRef.current.clientHeight || 600;

      const g = svg.append('g');

      // Zoom
      svg.call(d3.zoom<SVGSVGElement, unknown>().on('zoom', (e) => {
        g.attr('transform', e.transform);
      }) as any);

      // Links
      const nodeMap = new Map(data.nodes.map(n => [n.id, n]));
      const links = data.edges.map(e => ({
        source: e.source, target: e.target, rel: e.rel,
      }));

      const sim = d3.forceSimulation(data.nodes as any)
        .force('link', d3.forceLink(links).id((d: any) => d.id).distance(80))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(w / 2, h / 2))
        .force('collision', d3.forceCollide(28));

      // Arrow markers per edge type
      const relTypes = Array.from(new Set(data.edges.map(e => e.rel)));
      relTypes.forEach(rel => {
        svg.append('defs').append('marker')
          .attr('id', `arrow-${rel}`)
          .attr('markerWidth', 8).attr('markerHeight', 8)
          .attr('refX', 22).attr('refY', 4)
          .attr('orient', 'auto')
          .append('polygon')
          .attr('points', '0 0, 8 4, 0 8')
          .attr('fill', '#444466');
      });

      const link = g.append('g').selectAll('line')
        .data(links).join('line')
        .attr('stroke', '#2a2a44')
        .attr('stroke-width', 1.5)
        .attr('marker-end', (d: any) => `url(#arrow-${d.rel})`);

      const linkLabel = g.append('g').selectAll('text')
        .data(links).join('text')
        .attr('font-size', 8).attr('fill', '#555577').attr('text-anchor', 'middle');

      const dragBehavior = d3.drag<SVGGElement, any>()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; });

      const node = g.append('g').selectAll('g').data(data.nodes).join('g')
        .call(dragBehavior as any);

      node.append('circle')
        .attr('r', (d: any) => d.label === 'Service' ? 16 : 10)
        .attr('fill', (d: any) => getColor(d.label))
        .attr('fill-opacity', 0.18)
        .attr('stroke', (d: any) => getColor(d.label))
        .attr('stroke-width', d => (d as any).label === 'Service' ? 2 : 1.5);

      node.append('text')
        .attr('dy', 4).attr('text-anchor', 'middle')
        .attr('font-size', (d: any) => d.label === 'Service' ? 10 : 7)
        .attr('fill', (d: any) => getColor(d.label))
        .attr('font-weight', (d: any) => d.label === 'Service' ? '700' : '400')
        .text((d: any) => d.display?.split('::').pop()?.split('/').pop() || d.label.slice(0, 2));

      node.append('title').text((d: any) => `[${d.label}] ${d.display}`);

      sim.on('tick', () => {
        link
          .attr('x1', (d: any) => d.source.x)
          .attr('y1', (d: any) => d.source.y)
          .attr('x2', (d: any) => d.target.x)
          .attr('y2', (d: any) => d.target.y);
        linkLabel
          .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
          .attr('y', (d: any) => (d.source.y + d.target.y) / 2)
          .text((d: any) => d.rel);
        node.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
      });
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadGraph(); }, [loadGraph]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12,
                    background: 'rgba(13,13,24,0.8)', backdropFilter: 'blur(8px)' }}>
        <span style={{ fontSize: 16, opacity: 0.7 }} aria-hidden="true">◎</span>
        <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>Knowledge Graph</h2>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginLeft: 4 }}>— FalkorDB OpenCypher</span>
        {graphData && graphData.nodes.length > 0 && (
          <span className="pill pill-cyan" style={{ fontSize: '0.72rem', marginLeft: 8 }}>
            {graphData.nodes.length} nodes · {graphData.edges.length} edges
          </span>
        )}
        <button
          className="btn btn-ghost"
          onClick={loadGraph}
          aria-label="Refresh graph"
          style={{ marginLeft: 'auto', fontSize: '0.78rem', padding: '6px 12px' }}
        >
          ↺ Refresh
        </button>
      </div>
      {/* Legend */}
      <div style={{ padding: '8px 24px', display: 'flex', gap: 8, flexWrap: 'wrap', borderBottom: '1px solid var(--border)',
                    background: 'rgba(7,7,14,0.6)' }}>
        {Object.entries(LABEL_COLORS).map(([label, color]) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.72rem', color: 'var(--text-muted)',
                                    padding: '3px 8px', borderRadius: 99,
                                    background: `${color}10`, border: `1px solid ${color}28` }}>
            <div style={{ width: 7, height: 7, borderRadius: '50%', background: color }} />
            {label}
          </div>
        ))}
      </div>
      {loading && (
        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
                      color: 'var(--accent-cyan)', fontSize: '0.88rem', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ animation: 'spin-slow 1s linear infinite', display: 'inline-block' }}>⟳</span>
          Rendering graph…
        </div>
      )}
      {!loading && graphData && graphData.nodes.length === 0 && (
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          gap: 16, padding: 40, textAlign: 'center'
        }}>
          <div style={{ fontSize: 48, opacity: 0.3 }}>◎</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>No Graph Nodes Found</div>
          <p style={{ color: 'var(--text-muted)', maxWidth: 460, margin: 0, fontSize: '0.88rem', lineHeight: 1.6 }}>
            FalkorDB does not have graph topology loaded. Click below to seed the 6-service microservice demo graph with deliberate architecture violations.
          </p>
          <button
            className="btn btn-primary"
            disabled={seeding}
            onClick={async () => {
              setSeeding(true);
              try {
                await fetch(`${API}/graph/seed`, { method: 'POST' });
                await loadGraph();
              } catch (e) {
                console.error(e);
              } finally {
                setSeeding(false);
              }
            }}
          >
            {seeding ? 'Seeding FalkorDB…' : 'Seed Demo Graph (6 Services)'}
          </button>
        </div>
      )}
      <div style={{ flex: 1, position: 'relative' }} role="img" aria-label="Interactive microservice dependency graph">
        <svg id="graph-svg" ref={svgRef} style={{ width: '100%', height: '100%' }} />
      </div>
    </div>
  );
}

// ── Audit View ─────────────────────────────────────────────────────────────

function AuditView() {
  const [audit, setAudit] = useState<AuditResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<string>('all');

  const runAudit = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/review/audit`);
      const data = await res.json();
      setAudit(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { runAudit(); }, []);

  const filtered = audit?.violations.filter(v => filter === 'all' || v.severity === filter) || [];

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12,
                    background: 'rgba(13,13,24,0.8)', backdropFilter: 'blur(8px)' }}>
        <span style={{ fontSize: 16, opacity: 0.7 }} aria-hidden="true">⚑</span>
        <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>Architecture Audit</h2>
        <div style={{ display: 'flex', gap: 5, marginLeft: 12 }} role="group" aria-label="Filter by severity">
          {['all', 'high', 'medium', 'low'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              style={{
                padding: '4px 12px', borderRadius: 99, fontSize: '0.72rem', cursor: 'pointer', fontWeight: 600,
                background: filter === f
                  ? (f === 'high' ? 'rgba(255,107,107,0.15)' : f === 'medium' ? 'rgba(255,204,68,0.15)' : f === 'low' ? 'rgba(61,224,122,0.12)' : 'rgba(94,207,255,0.15)')
                  : 'transparent',
                border: `1px solid ${filter === f
                  ? (f === 'high' ? 'rgba(255,107,107,0.35)' : f === 'medium' ? 'rgba(255,204,68,0.35)' : f === 'low' ? 'rgba(61,224,122,0.3)' : 'rgba(94,207,255,0.3)')
                  : 'var(--border)'}`,
                color: filter === f
                  ? (f === 'high' ? 'var(--accent-red)' : f === 'medium' ? 'var(--accent-amber)' : f === 'low' ? 'var(--accent-green)' : 'var(--accent-cyan)')
                  : 'var(--text-dim)',
              }}
            >
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <button
          className="btn btn-ghost"
          onClick={runAudit}
          disabled={loading}
          aria-label={loading ? 'Audit running' : 'Run architecture audit'}
          style={{ marginLeft: 'auto', fontSize: '0.78rem', padding: '6px 14px' }}
        >
          {loading ? '⟳ Running…' : '▶ Run Audit'}
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
        {audit && (
          <div style={{ marginBottom: 20, padding: '12px 18px', borderRadius: 10, display: 'flex', gap: 24,
                        background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Total Violations</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, color: audit.total_violations > 0 ? 'var(--accent-red)' : 'var(--accent-green)' }}>
                {audit.total_violations}
              </div>
            </div>
            {['high', 'medium', 'low'].map(sev => (
              <div key={sev}>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)', textTransform: 'uppercase' }}>{sev}</div>
                <div style={{ fontSize: '1.8rem', fontWeight: 700 }}
                     className={sev === 'high' ? 'neon-cyan' : ''}>
                  {audit.violations.filter(v => v.severity === sev).length}
                </div>
              </div>
            ))}
          </div>
        )}

        {filtered.length === 0 && !loading && (
          <div style={{ textAlign: 'center', color: 'var(--text-dim)', padding: 60 }}>
            {audit ? '✅ No violations found.' : 'Run an audit to see violations.'}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {filtered.map((v, i) => <ViolationCard key={i} v={v} index={i} />)}
        </div>
      </div>
    </div>
  );
}

// ── PR Review View ─────────────────────────────────────────────────────────

function ReviewView() {
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const runDemo = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/review/demo-review`);
      const data = await res.json();
      setResult(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>PR Architecture Review</h2>
        <button onClick={runDemo} disabled={loading}
                style={{ marginLeft: 'auto', padding: '6px 16px', borderRadius: 8, fontSize: '0.8rem',
                         background: 'linear-gradient(135deg, rgba(118,227,255,0.15), rgba(167,139,250,0.15))',
                         border: '1px solid var(--border)', color: 'var(--text-primary)', cursor: 'pointer', fontWeight: 600 }}>
          {loading ? '⟳ Reviewing…' : '▶ Run Demo Review (PR #42)'}
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
        {!result && !loading && (
          <div style={{ textAlign: 'center', color: 'var(--text-dim)', padding: 60 }}>
            <div style={{ fontSize: '3rem', marginBottom: 16 }}>⤳</div>
            <div style={{ fontSize: '1.1rem', marginBottom: 8, color: 'var(--text-muted)' }}>
              Ready to review PR
            </div>
            <div style={{ fontSize: '0.85rem' }}>
              Click "Run Demo Review" to see FalkorDB graph branching in action
            </div>
          </div>
        )}

        {result && (
          <div className="animate-fade-in">
            {/* Summary header */}
            <div style={{ padding: '20px 24px', borderRadius: 12, marginBottom: 20,
                          background: 'linear-gradient(135deg, rgba(118,227,255,0.05), rgba(167,139,250,0.05))',
                          border: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>PR</div>
                  <div style={{ fontWeight: 700, color: 'var(--accent-cyan)' }}>{result.pr_id}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>New Violations</div>
                  <div style={{ fontWeight: 700, fontSize: '1.5rem',
                                color: result.new_violation_count > 0 ? 'var(--accent-red)' : 'var(--accent-green)' }}>
                    {result.new_violation_count}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>Blast Radius</div>
                  <div style={{ fontWeight: 700, fontSize: '1.5rem', color: 'var(--accent-amber)' }}>
                    {result.blast_radius?.length || 0} services
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Touched:</span>
                {result.touched_services?.map((s: string) => (
                  <span key={s} style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: 12,
                    background: 'rgba(118,227,255,0.1)', border: '1px solid rgba(118,227,255,0.2)',
                    color: 'var(--accent-cyan)' }}>{s}</span>
                ))}
              </div>
              {result.blast_radius?.length > 0 && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Blast radius:</span>
                  {result.blast_radius.map((s: string) => (
                    <span key={s} style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: 12,
                      background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.2)',
                      color: 'var(--accent-amber)' }}>{s}</span>
                  ))}
                </div>
              )}
            </div>

            {/* Violations */}
            <div style={{ fontWeight: 600, marginBottom: 12, color: 'var(--text-muted)', fontSize: '0.85rem',
                          textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              New Violations ({result.new_violation_count})
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {result.new_violations?.map((v: Violation, i: number) => (
                <ViolationCard key={i} v={v} index={i} />
              ))}
              {result.new_violation_count === 0 && (
                <div style={{ textAlign: 'center', padding: 40, color: 'var(--accent-green)' }}>
                  ✅ This PR introduces no new architecture violations
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Principles View ────────────────────────────────────────────────────────

function PrinciplesView() {
  const [principles, setPrinciples] = useState<any[]>([]);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [mineInput, setMineInput] = useState('');
  const [mining, setMining] = useState(false);
  const [mineResult, setMineResult] = useState<any>(null);

  useEffect(() => {
    fetch(`${API}/principles/list`).then(r => r.json()).then(d => setPrinciples(d.principles || []));
    fetch(`${API}/principles/candidates`).then(r => r.json()).then(d => setCandidates(d.candidates || []));
  }, []);

  const mine = async () => {
    if (!mineInput.trim()) return;
    setMining(true);
    setMineResult(null);
    try {
      const res = await fetch(`${API}/principles/mine`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ natural_language_rule: mineInput }),
      });
      const data = await res.json();
      setMineResult(data);
      if (data.success) {
        const r2 = await fetch(`${API}/principles/candidates`);
        const d2 = await r2.json();
        setCandidates(d2.candidates || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setMining(false);
    }
  };

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
      {/* Mine new rule */}
      <div className="glass" style={{ padding: '20px 24px', marginBottom: 24 }}>
        <div style={{ fontWeight: 600, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: 'var(--nvidia-green)' }}>✦</span>
          Mine New Principle with Nemotron Super
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <input
            value={mineInput}
            onChange={e => setMineInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && mine()}
            placeholder="e.g. Services must not call each other synchronously during peak hours"
            style={{ flex: 1, padding: '10px 14px', borderRadius: 8, background: 'var(--bg-primary)',
                     border: '1px solid var(--border)', color: 'var(--text-primary)', fontSize: '0.88rem',
                     outline: 'none' }}
          />
          <button onClick={mine} disabled={mining || !mineInput.trim()}
                  style={{ padding: '10px 20px', borderRadius: 8, fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer',
                           background: mining ? 'var(--bg-card)' : 'linear-gradient(135deg, var(--accent-cyan), var(--accent-violet))',
                           border: 'none', color: mining ? 'var(--text-dim)' : '#000' }}>
            {mining ? '⟳ Mining…' : '⚡ Mine'}
          </button>
        </div>
        {mineResult && (
          <div style={{ marginTop: 14, padding: '12px 16px', borderRadius: 8,
                        background: mineResult.success ? 'rgba(74,222,128,0.06)' : 'rgba(248,113,113,0.06)',
                        border: `1px solid ${mineResult.success ? 'rgba(74,222,128,0.2)' : 'rgba(248,113,113,0.2)'}` }}>
            {mineResult.success ? (
              <>
                <div style={{ color: 'var(--accent-green)', fontWeight: 600, marginBottom: 8 }}>
                  ✅ Mined: [{mineResult.candidate?.id}]
                </div>
                <div className="code-block">{mineResult.candidate?.query}</div>
              </>
            ) : (
              <div style={{ color: 'var(--accent-red)' }}>
                ⚠️ {mineResult.detail || 'Mining failed. Set NVIDIA_API_KEY to enable LLM features.'}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Confirmed principles */}
      <div style={{ fontWeight: 600, marginBottom: 12, fontSize: '0.85rem', textTransform: 'uppercase',
                    letterSpacing: '0.08em', color: 'var(--text-muted)' }}>
        Confirmed Principles ({principles.length})
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 32 }}>
        {principles.map((p, i) => (
          <div key={p.id} className="violation-card" style={{ animationDelay: `${i * 0.04}s` }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
              <div>
                <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                  <span className={`badge-${p.severity}`} style={{ fontSize: '0.72rem', fontWeight: 700, padding: '2px 8px', borderRadius: 20 }}>
                    {p.severity.toUpperCase()}
                  </span>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.8rem', color: 'var(--accent-cyan)', fontWeight: 600 }}>
                    {p.id}
                  </span>
                  <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: 20,
                    background: 'rgba(167,139,250,0.1)', color: 'var(--accent-violet)', border: '1px solid rgba(167,139,250,0.2)' }}>
                    {p.source}
                  </span>
                </div>
                <div style={{ fontSize: '0.88rem', fontWeight: 500, lineHeight: 1.5 }}>{p.statement}</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)', marginTop: 6 }}>💡 {p.fix_hint}</div>
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <div className="code-block" style={{ fontSize: '0.75rem' }}>{p.query?.trim()}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Candidates */}
      {candidates.length > 0 && (
        <>
          <div style={{ fontWeight: 600, marginBottom: 12, fontSize: '0.85rem', textTransform: 'uppercase',
                        letterSpacing: '0.08em', color: 'var(--text-muted)' }}>
            Candidate Principles ({candidates.length}) — Awaiting Human Review
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {candidates.map((p, i) => (
              <div key={p.id} className="violation-card" style={{ animationDelay: `${i * 0.04}s`,
                    borderColor: 'rgba(251,191,36,0.2)', background: 'rgba(251,191,36,0.03)' }}>
                <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                  <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '2px 8px', borderRadius: 20,
                    background: 'rgba(251,191,36,0.15)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.3)' }}>
                    CANDIDATE
                  </span>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.8rem', color: 'var(--accent-cyan)', fontWeight: 600 }}>{p.id}</span>
                </div>
                <div style={{ fontSize: '0.88rem', fontWeight: 500 }}>{p.statement}</div>
                <div className="code-block" style={{ marginTop: 10, fontSize: '0.75rem' }}>{p.query?.trim()}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Dashboard View ─────────────────────────────────────────────────────────

function DashboardView({ onNav }: { onNav: (p: string) => void }) {
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API}/graph/stats`).then(r => r.json()),
      fetch(`${API}/health`).then(r => r.json()),
    ]).then(([s, h]) => { setStats(s); setHealth(h); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>
      {/* Hero */}
      <div className="animate-fade-up" style={{ marginBottom: 28, position: 'relative' }}>
        <div style={{
          position: 'absolute', top: -10, left: -10, right: -10, bottom: -10,
          background: 'radial-gradient(ellipse at 20% 50%, rgba(94,207,255,0.04) 0%, transparent 60%)',
          pointerEvents: 'none',
        }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <span className="pill pill-green" style={{ fontSize: '0.65rem' }}>● Live</span>
          <span className="pill pill-violet" style={{ fontSize: '0.65rem' }}>NVIDIA × FalkorDB Hackathon 2026</span>
        </div>
        <h1 style={{ fontSize: '2.2rem', fontWeight: 900, margin: '8px 0 10px', letterSpacing: '-0.04em', lineHeight: 1.1 }}>
          Architecture <span className="grad-cyan-violet">Guardian</span>
        </h1>
        <p style={{ color: 'var(--text-muted)', margin: 0, fontSize: '0.92rem', lineHeight: 1.7, maxWidth: 560 }}>
          Graph-powered microservice governance using <strong style={{ color: 'var(--accent-cyan)' }}>FalkorDB OpenCypher</strong> + principle mining &amp; AI remediation via <strong style={{ color: 'var(--nvidia-green)' }}>NVIDIA Nemotron</strong>.
        </p>
      </div>

      {/* Health status bar */}
      {health && (
        <div className="glass animate-fade-up" style={{ marginBottom: 24, padding: '12px 20px',
              display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center' }}
             role="status" aria-live="polite" aria-label="System health status">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className={`status-dot ${health.status === 'ok' ? 'online' : 'offline'}`} />
            <span style={{ fontSize: '0.82rem', fontWeight: 600 }}>
              {health.engine === 'falkor' ? '⬡ FalkorDB' : '◈ Memory'} {health.status === 'ok' ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <div style={{ height: 16, width: 1, background: 'var(--border)' }} />
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Graph: <span style={{ color: 'var(--accent-cyan)', fontFamily: 'JetBrains Mono, monospace', fontSize: '0.78rem' }}>{health.graph}</span>
          </div>
          <div style={{ height: 16, width: 1, background: 'var(--border)' }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            <div className={`status-dot ${health.llm_available ? 'online' : 'offline'}`} style={{ width: 6, height: 6, animation: 'none' }} />
            LLM: <span style={{ color: health.llm_available ? 'var(--accent-green)' : 'var(--accent-red)', fontWeight: 600 }}>
              {health.llm_available ? 'Nemotron Ready' : 'No API Key'}
            </span>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>{health.nodes} nodes · {health.edges} edges</span>
          </div>
        </div>
      )}

      {/* Stats grid */}
      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 28 }}>
          {[...Array(4)].map((_, i) => <div key={i} className="skeleton" style={{ height: 100 }} />)}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 14, marginBottom: 28 }}>
          <StatCard label="Graph Nodes" value={stats?.node_count ?? 0} color="var(--accent-cyan)" icon="◎" />
          <StatCard label="Graph Edges" value={stats?.edge_count ?? 0} color="var(--accent-violet)" icon="↔" />
          <StatCard label="Services" value={stats?.services.length ?? 0} color="var(--accent-green)" icon="⬡" />
          <StatCard label="Node Types" value={stats?.labels.length ?? 0} color="var(--accent-amber)" icon="⊛" />
        </div>
      )}

      {/* Quick actions */}
      <div style={{ fontWeight: 600, marginBottom: 14, fontSize: '0.85rem', textTransform: 'uppercase',
                    letterSpacing: '0.08em', color: 'var(--text-muted)' }}>Quick Actions</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 28 }}>
        {[
          { icon: '⬡', label: 'View Graph', sub: 'D3 force visualization', page: 'graph', color: 'var(--accent-cyan)' },
          { icon: '⚑', label: 'Run Audit', sub: 'All architecture violations', page: 'audit', color: 'var(--accent-red)' },
          { icon: '⤳', label: 'PR Review', sub: 'Demo review with diff', page: 'review', color: 'var(--accent-violet)' },
          { icon: '⊛', label: 'Principles', sub: 'Mine new rules w/ Nemotron', page: 'principles', color: 'var(--accent-green)' },
        ].map(a => (
          <div key={a.page} className="stat-card" style={{ cursor: 'pointer' }} onClick={() => onNav(a.page)}>
            <div style={{ fontSize: '1.8rem', color: a.color, marginBottom: 10 }}>{a.icon}</div>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{a.label}</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>{a.sub}</div>
          </div>
        ))}
      </div>

      {/* Services + label breakdown */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div className="glass" style={{ padding: '16px 20px' }}>
            <div style={{ fontWeight: 600, marginBottom: 12, fontSize: '0.85rem', color: 'var(--text-muted)',
                          textTransform: 'uppercase', letterSpacing: '0.08em' }}>Services</div>
            {stats.services.map(s => (
              <div key={s.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0',
                                         borderBottom: '1px solid var(--border)', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--accent-cyan)', fontFamily: 'monospace' }}>{s.name}</span>
                <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem' }}>{s.language}</span>
              </div>
            ))}
          </div>
          <div className="glass" style={{ padding: '16px 20px' }}>
            <div style={{ fontWeight: 600, marginBottom: 12, fontSize: '0.85rem', color: 'var(--text-muted)',
                          textTransform: 'uppercase', letterSpacing: '0.08em' }}>Node Types</div>
            {stats.labels.map(l => (
              <div key={l.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                          padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: getColor(l.label), opacity: 0.8 }} />
                  <span style={{ fontSize: '0.85rem' }}>{l.label}</span>
                </div>
                <span style={{ fontFamily: 'monospace', fontSize: '0.82rem', color: 'var(--accent-violet)' }}>{l.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main App ───────────────────────────────────────────────────────────────

export default function App() {
  const [page, setPage] = useState('dashboard');

  const renderPage = () => {
    switch (page) {
      case 'graph': return <GraphView />;
      case 'audit': return <AuditView />;
      case 'review': return <ReviewView />;
      case 'principles': return <PrinciplesView />;
      default: return <DashboardView onNav={setPage} />;
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar active={page} onNav={setPage} />
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden',
                     background: 'var(--bg-primary)' }} role="main">
        {/* Top bar */}
        <div style={{ padding: '10px 24px', borderBottom: '1px solid var(--border)',
                      display: 'flex', alignItems: 'center', gap: 12,
                      background: 'rgba(13,13,24,0.9)', backdropFilter: 'blur(12px)',
                      position: 'sticky', top: 0, zIndex: 10 }}>
          {/* Breadcrumb */}
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Archwarden</span>
            <span style={{ color: 'var(--border-bright)', fontSize: '0.72rem' }}>›</span>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>
              {page.charAt(0).toUpperCase() + page.slice(1)}
            </span>
          </div>
          {/* Right side badges */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="pill pill-green" style={{ fontSize: '0.65rem' }}>⬡ NVIDIA Nemotron</span>
            <span className="pill pill-cyan" style={{ fontSize: '0.65rem' }}>FalkorDB</span>
          </div>
        </div>

        {/* Page content */}
        {renderPage()}
      </main>
    </div>
  );
}
