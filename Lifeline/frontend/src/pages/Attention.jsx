import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listDocuments } from '../api/client'
import PriorityBadge from '../components/PriorityBadge'
import './dashboard.css'

export default function Attention() {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listDocuments().then(({ documents }) => setDocuments(documents)).finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="muted">Loading…</p>

  const grouped = ['urgent', 'needs_review', 'attention_soon', 'upcoming', 'safe'].map((level) => ({
    level,
    items: documents.filter((d) => d.priority?.level === level),
  })).filter((g) => g.items.length > 0)

  const titles = {
    urgent: 'Urgent', needs_review: 'Needs review', attention_soon: 'Attention soon',
    upcoming: 'Upcoming', safe: 'Safe',
  }

  return (
    <div>
      <div className="dashboard-heading">
        <h1>Attention</h1>
        <p className="muted">Every dated item across your documents, ranked by how soon it needs you.</p>
      </div>

      {grouped.length === 0 && <p className="empty-note">Nothing to show yet — upload a document to get started.</p>}

      {grouped.map((g) => (
        <section key={g.level}>
          <h2 className="section-title">{titles[g.level]}</h2>
          <ul className="item-list">
            {g.items.map((doc) => (
              <li key={doc.document_id}>
                <Link to={`/documents/${doc.document_id}`} className="item-row" style={{ borderLeftColor: `var(--${levelVar(doc.priority.level)})` }}>
                  <div className="item-row-main">
                    <div className="item-title">{doc.title}</div>
                    <div className="muted item-reason">{doc.priority.reason}</div>
                  </div>
                  <PriorityBadge level={doc.priority.level} compact />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function levelVar(level) {
  return { urgent: 'urgent', attention_soon: 'soon', needs_review: 'review', upcoming: 'upcoming', safe: 'signal' }[level] || 'line'
}
