import { useEffect, useState } from 'react'
import { useLocation, useNavigate, Link } from 'react-router-dom'
import { listDocuments } from '../api/client'
import './emergency.css'

export default function ActionPlan() {
  const { state } = useLocation()
  const navigate = useNavigate()
  const plan = state?.plan
  const [docsById, setDocsById] = useState(plan?.documents_by_id || {})

  useEffect(() => {
    if (!plan || plan.documents_by_id) return // mock mode already provides this
    listDocuments().then(({ documents }) => {
      setDocsById(Object.fromEntries(documents.map((d) => [d.document_id, d])))
    })
  }, [plan])

  if (!plan) {
    return (
      <div>
        <p className="muted">No plan loaded.</p>
        <Link to="/emergency" className="btn btn-secondary">Back to situations</Link>
      </div>
    )
  }

  return (
    <div>
      <button className="link-btn" style={{ marginBottom: '0.6rem' }} onClick={() => navigate('/emergency')}>
        ← Choose a different situation
      </button>

      <div className="dashboard-heading">
        <h1>Your action plan</h1>
        <p className="muted">{plan.summary}</p>
      </div>

      {plan.missing_information?.length > 0 && (
        <div className="panel conflict-panel" style={{ marginBottom: '1.2rem' }}>
          <strong>What LifeLine couldn't find</strong>
          <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem' }}>
            {plan.missing_information.map((m, i) => <li key={i} className="muted">{m}</li>)}
          </ul>
        </div>
      )}

      <div className="panel">
        <h2 style={{ fontSize: '1rem', marginBottom: 0 }}>Do this first</h2>
        <div>
          {plan.steps.map((step) => (
            <div className="plan-step" key={step.order}>
              <div className="plan-step-num">{step.order}</div>
              <div>
                <div style={{ fontWeight: 600 }}>{step.action}</div>
                <div className="muted" style={{ fontSize: '0.87rem', marginTop: '0.15rem' }}>{step.why}</div>
                {step.source_document_ids?.length > 0 && (
                  <div style={{ marginTop: '0.4rem' }}>
                    {step.source_document_ids.map((id) => (
                      <Link key={id} to={`/documents/${id}`} className="source-chip">
                        📄 {docsById[id]?.title || 'Source document'}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {plan.relevant_documents?.length > 0 && (
        <section>
          <h2 className="section-title">Relevant stored information</h2>
          <ul className="item-list">
            {plan.relevant_documents.map((id) => {
              const d = docsById[id]
              if (!d) return null
              return (
                <li key={id}>
                  <Link to={`/documents/${id}`} className="item-row doc-row">
                    <div className="item-row-main">
                      <div className="item-title">{d.title}</div>
                      <div className="muted item-reason">{d.provider || d.document_type}</div>
                    </div>
                  </Link>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      <p className="muted" style={{ fontSize: '0.8rem', marginTop: '1.5rem', borderTop: '1px solid var(--line)', paddingTop: '1rem' }}>
        {plan.disclaimer}
      </p>
    </div>
  )
}
