import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { listDocuments, requestUploadUrl, uploadToPresignedUrl, processDocument } from '../api/client'
import PriorityBadge from '../components/PriorityBadge'
import './dashboard.css'
import './documents.css'

const DOC_TYPE_LABEL = {
  insurance: 'Insurance', identity: 'Identity', passport: 'Passport', warranty: 'Warranty',
  bill: 'Bill', subscription: 'Subscription', certificate: 'Certificate', medical: 'Medical',
  financial: 'Financial', legal: 'Legal', other: 'Other',
}

export default function Documents() {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploads, setUploads] = useState([]) // in-flight upload status rows
  const fileInputRef = useRef(null)

  async function refresh() {
    const { documents } = await listDocuments()
    setDocuments(documents)
  }

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [])

  async function handleFiles(files) {
    for (const file of Array.from(files)) {
      const uploadRowId = `${file.name}-${Date.now()}`
      setUploads((u) => [...u, { id: uploadRowId, filename: file.name, stage: 'uploading' }])
      try {
        const { document_id, upload_url } = await requestUploadUrl(file)
        if (upload_url) await uploadToPresignedUrl(upload_url, file)
        setUploads((u) => u.map((r) => (r.id === uploadRowId ? { ...r, stage: 'processing' } : r)))
        await processDocument(document_id, file.name)
        setUploads((u) => u.filter((r) => r.id !== uploadRowId))
        await refresh()
      } catch (err) {
        setUploads((u) => u.map((r) => (r.id === uploadRowId ? { ...r, stage: 'failed', error: err.message } : r)))
      }
    }
  }

  return (
    <div>
      <div className="dashboard-heading">
        <h1>Documents</h1>
        <p className="muted">Upload insurance, IDs, warranties, bills, and certificates — LifeLine reads them for you.</p>
      </div>

      <div
        className="dropzone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files) }}
        onClick={() => fileInputRef.current?.click()}
      >
        <p><strong>Drop a document here</strong>, or click to choose a file</p>
        <p className="muted" style={{ margin: 0 }}>PDF, PNG, JPEG, or WebP — up to 15MB</p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.webp"
          multiple
          hidden
          onChange={(e) => e.target.files.length && handleFiles(e.target.files)}
        />
      </div>

      {uploads.length > 0 && (
        <ul className="item-list" style={{ marginTop: '1rem' }}>
          {uploads.map((u) => (
            <li key={u.id} className="item-row" style={{ borderLeftColor: u.stage === 'failed' ? 'var(--urgent)' : 'var(--upcoming)' }}>
              <div className="item-row-main">
                <div className="item-title">{u.filename}</div>
                <div className="muted item-reason">
                  {u.stage === 'uploading' && 'Uploading…'}
                  {u.stage === 'processing' && 'Reading document with Bedrock…'}
                  {u.stage === 'failed' && `Failed: ${u.error}`}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <h2 className="section-title">All documents</h2>
      {loading ? (
        <p className="muted">Loading…</p>
      ) : documents.length === 0 ? (
        <p className="empty-note">No documents yet — upload one above to see LifeLine in action.</p>
      ) : (
        <ul className="item-list">
          {documents.map((doc) => (
            <li key={doc.document_id}>
              <Link to={`/documents/${doc.document_id}`} className="item-row doc-row">
                <div className="item-row-main">
                  <div className="item-title">{doc.title}</div>
                  <div className="muted item-reason">
                    {DOC_TYPE_LABEL[doc.document_type] || 'Other'}{doc.provider ? ` · ${doc.provider}` : ''}
                  </div>
                </div>
                {doc.status === 'processed' ? (
                  <PriorityBadge level={doc.priority?.level} compact />
                ) : (
                  <span className="muted">{doc.status}</span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
