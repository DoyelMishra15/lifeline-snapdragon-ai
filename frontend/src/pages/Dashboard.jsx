import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listDocuments } from '../api/client'
import PriorityBadge from '../components/PriorityBadge'
import './dashboard.css'

export default function Dashboard() {
  const [state, setState] = useState({ loading: true, documents: [], conflicts: [], recentEvents: [], error: null })

  useEffect(() => {
    let cancelled = false
    listDocuments()
      .then(({ documents, conflicts, recent_events }) => {
        if (!cancelled) setState({ loading: false, documents, conflicts, recentEvents: recent_events || [], error: null })
      })
      .catch((err) => { if (!cancelled) setState({ loading: false, documents: [], conflicts: [], recentEvents: [], error: err.message }) })
    return () => { cancelled = true }
  }, [])

  const { loading, documents, conflicts, recentEvents, error } = state

  const importantNow = documents.filter((d) => ['urgent', 'needs_review'].includes(d.priority?.level))
  const upcoming = documents.filter((d) => ['attention_soon', 'upcoming'].includes(d.priority?.level))
  // recentEvents comes from the EventBridge-driven attention sweep
  // (backend/handlers/reminders.py); fall back to deriving something
  // from the document list itself only if the sweep hasn't produced
  // anything yet (e.g. brand-new account, first Lambda run pending).
  const recent = recentEvents.length > 0
    ? recentEvents.map((e) => ({
        document_id: e.document_id,
        title: e.title,
        priority: { level: e.priority_level, reason: e.reason },
        status: 'processed',
      }))
    : [...documents].sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || '')).slice(0, 5)

  if (loading) return <p className="muted">Loading your dashboard…</p>
  if (error) return <p className="form-error">{error}</p>

  return (
    <div className="dashboard">
      <div className="dashboard-heading">
        <h1>What needs your attention</h1>
        <p className="muted">{documents.length} document{documents.length === 1 ? '' : 's'} on file.</p>
      </div>

      {conflicts.length > 0 && (
        <div className="panel conflict-panel">
          <strong>⚠ Conflict detected</strong>
          {conflicts.map((c, i) => (
            <p key={i} className="muted" style={{ margin: '0.4rem 0 0' }}>
              Two stored {c.document_type} documents{c.provider ? ` from ${c.provider}` : ''} give different
              expiry dates ({c.conflicting_dates.join(' vs. ')}). LifeLine will not silently choose one —
              please review both.
            </p>
          ))}
        </div>
      )}

      <section>
        <h2 className="section-title">Attention needed</h2>
        {importantNow.length === 0 ? (
          <p className="empty-note">Nothing urgent right now. New uploads and approaching dates will show up here.</p>
        ) : (
          <ItemList items={importantNow} />
        )}
      </section>

      <section>
        <h2 className="section-title">Upcoming</h2>
        {upcoming.length === 0 ? (
          <p className="empty-note">No upcoming deadlines in the next 90 days.</p>
        ) : (
          <ItemList items={upcoming} />
        )}
      </section>

      <section>
        <h2 className="section-title">Recent activity</h2>
        {recent.length === 0 ? (
          <p className="empty-note">Upload your first document to get started.</p>
        ) : (
          <ItemList items={recent} showStatus />
        )}
      </section>

      <Link to="/documents" className="btn btn-secondary" style={{ display: 'inline-block', marginTop: '0.5rem' }}>
        View all documents
      </Link>
    </div>
  )
}

function ItemList({ items, showStatus }) {
  return (
    <ul className="item-list">
      {items.map((doc) => (
        <li key={doc.document_id}>
          <Link to={`/documents/${doc.document_id}`} className="item-row" style={{ borderLeftColor: `var(--${levelVar(doc.priority?.level)})` }}>
            <div className="item-row-main">
              <div className="item-title">{doc.title}</div>
              <div className="muted item-reason">
                {showStatus && doc.status !== 'processed' ? statusLabel(doc.status) : doc.priority?.reason}
              </div>
            </div>
            <PriorityBadge level={doc.priority?.level} compact />
          </Link>
        </li>
      ))}
    </ul>
  )
}

function levelVar(level) {
  return { urgent: 'urgent', attention_soon: 'soon', needs_review: 'review', upcoming: 'upcoming', safe: 'signal' }[level] || 'line'
}

function statusLabel(status) {
  return { uploaded: 'Uploaded — waiting to process', processing: 'Processing…', failed: 'Processing failed', needs_review: 'Needs review' }[status] || status
}
