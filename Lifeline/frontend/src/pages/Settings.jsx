import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { getProfile, putProfile, triggerReminderSweep } from '../api/client'
import './dashboard.css'

export default function Settings() {
  const { user } = useAuth()
  const [name, setName] = useState('')
  const [contactName, setContactName] = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)
  const [sweepStatus, setSweepStatus] = useState(null)
  const [sweeping, setSweeping] = useState(false)

  useEffect(() => {
    getProfile().then((p) => {
      setName(p.display_name || '')
      setContactName(p.emergency_contact?.name || '')
      setContactPhone(p.emergency_contact?.phone || '')
    }).finally(() => setLoading(false))
  }, [])

  async function save(e) {
    e.preventDefault()
    setSaved(false)
    await putProfile({
      display_name: name,
      emergency_contact: contactName || contactPhone ? { name: contactName, phone: contactPhone } : undefined,
    })
    setSaved(true)
  }

  async function runSweep() {
    setSweeping(true)
    setSweepStatus(null)
    try {
      const result = await triggerReminderSweep()
      setSweepStatus(result.body || 'Sweep complete.')
    } catch (err) {
      setSweepStatus(`Sweep failed: ${err.message}`)
    } finally {
      setSweeping(false)
    }
  }

  if (loading) return <p className="muted">Loading…</p>

  return (
    <div>
      <div className="dashboard-heading">
        <h1>Settings</h1>
        <p className="muted">Signed in as {user?.email}</p>
      </div>

      <form className="panel" onSubmit={save} style={{ maxWidth: 420, display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
        <div>
          <label className="field-label">Display name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="How LifeLine should address you" />
        </div>

        <div>
          <h3 style={{ fontSize: '0.95rem', margin: '0.4rem 0 0.2rem' }}>Emergency contact</h3>
          <p className="muted" style={{ fontSize: '0.82rem', margin: '0 0 0.6rem' }}>
            Surfaced during emergency/situation mode as someone who may need to help.
          </p>
          <label className="field-label">Name</label>
          <input value={contactName} onChange={(e) => setContactName(e.target.value)} placeholder="Contact's name" />
        </div>
        <div>
          <label className="field-label">Phone</label>
          <input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} placeholder="Contact's phone number" />
        </div>

        <button className="btn btn-signal" type="submit" style={{ alignSelf: 'flex-start' }}>Save</button>
        {saved && <p className="muted" style={{ margin: 0 }}>Saved.</p>}
      </form>

      <div className="panel" style={{ maxWidth: 420, marginTop: '1.2rem' }}>
        <h3 style={{ fontSize: '0.95rem', margin: '0 0 0.3rem' }}>Attention sweep</h3>
        <p className="muted" style={{ fontSize: '0.82rem', margin: '0 0 0.7rem' }}>
          In production this runs automatically once a day via Amazon EventBridge. Trigger
          it manually here to see it update your Dashboard's "Recent activity" right away.
        </p>
        <button className="btn btn-secondary" onClick={runSweep} disabled={sweeping}>
          {sweeping ? 'Running…' : 'Run attention sweep now'}
        </button>
        {sweepStatus && <p className="muted" style={{ margin: '0.6rem 0 0', fontSize: '0.82rem' }}>{sweepStatus}</p>}
      </div>
    </div>
  )
}
