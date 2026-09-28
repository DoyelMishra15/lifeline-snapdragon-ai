import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getDocument } from '../api/client'
import PriorityBadge from '../components/PriorityBadge'
import './dashboard.css'
import './documents.css'

export default function DocumentDetail() {
  const { documentId } = useParams()
  const [doc, setDoc] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getDocument(documentId).then(setDoc).catch((e) => setError(e.message))
  }, [documentId])

  if (error) return <p className="form-error">{error}</p>
  if (!doc) return <p className="muted">Loading…</p>

  return (
    <div>
      <Link to="/documents" className="muted" style={{ textDecoration: 'none', fontSize: '0.85rem' }}>← All documents</Link>

      <div className="dashboard-heading" style={{ marginTop: '0.6rem', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem' }}>
        <div>
          <h1>{doc.title}</h1>
          <p className="muted">{doc.provider || 'No provider detected'}</p>
        </div>
        {doc.priority?.level && <PriorityBadge level={doc.priority.level} />}
      </div>

      {doc.priority?.reason && (
        <div className="panel" style={{ marginBottom: '1.2rem', borderLeftWidth: 3, borderLeftColor: 'var(--signal)' }}>
          <strong style={{ fontSize: '0.9rem' }}>Why this priority</strong>
          <p className="muted" style={{ margin: '0.3rem 0 0' }}>{doc.priority.reason}</p>
        </div>
      )}

      {doc.warnings?.length > 0 && (
        <div className="panel conflict-panel" style={{ marginBottom: '1.2rem' }}>
          <strong>⚠ Warnings</strong>
          <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem' }}>
            {doc.warnings.map((w, i) => <li key={i} className="muted">{w}</li>)}
          </ul>
        </div>
      )}

      <div className="detail-grid">
        <div className="panel">
          <h3 style={{ fontSize: '0.95rem' }}>Details</h3>
          <dl className="detail-list">
            <dt>Type</dt><dd>{doc.document_type}</dd>
            {doc.amount && (<><dt>Amount</dt><dd>{doc.amount}</dd></>)}
            {doc.expiry_date && (<><dt>Expiry / key date</dt><dd>{doc.expiry_date}</dd></>)}
            <dt>Confidence</dt><dd>{doc.confidence != null ? `${Math.round(doc.confidence * 100)}%` : '—'}</dd>
          </dl>

          {doc.important_dates?.length > 0 && (
            <>
              <h3 style={{ fontSize: '0.95rem', marginTop: '1.2rem' }}>Important dates</h3>
              <ul className="plain-list">
                {doc.important_dates.map((d, i) => (
                  <li key={i}>{d.date} — {d.description || d.type}</li>
                ))}
              </ul>
            </>
          )}

          {doc.actions?.length > 0 && (
            <>
              <h3 style={{ fontSize: '0.95rem', marginTop: '1.2rem' }}>Suggested actions</h3>
              <ul className="plain-list">
                {doc.actions.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </>
          )}
        </div>

        <div className="panel">
          <h3 style={{ fontSize: '0.95rem' }}>Source</h3>
          <p className="muted" style={{ fontSize: '0.85rem' }}>{doc.filename || 'Original file'}</p>
          {doc.source_url ? (
            <a className="btn btn-secondary" href={doc.source_url} target="_blank" rel="noreferrer">Open original document</a>
          ) : (
            <p className="muted" style={{ fontSize: '0.82rem' }}>
              {doc.status === 'processed'
                ? 'Source preview unavailable in this demo session.'
                : 'The original file will be linked here once processing completes.'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
