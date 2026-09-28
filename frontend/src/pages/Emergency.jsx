import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { generateEmergencyPlan } from '../api/client'
import './emergency.css'

const SITUATIONS = [
  { key: 'lost_phone', label: 'Lost my phone', icon: '📱' },
  { key: 'lost_wallet', label: 'Lost my wallet / documents', icon: '👛' },
  { key: 'medical_emergency', label: 'Hospital / medical emergency', icon: '🏥' },
  { key: 'temporarily_unavailable', label: "I'm temporarily unavailable", icon: '🌙' },
  { key: 'travel_emergency', label: 'Travel emergency', icon: '✈️' },
  { key: 'other', label: 'Other', icon: '❓' },
]

export default function Emergency() {
  const navigate = useNavigate()
  const [loadingKey, setLoadingKey] = useState(null)
  const [error, setError] = useState(null)

  async function select(key) {
    setError(null)
    setLoadingKey(key)
    try {
      const plan = await generateEmergencyPlan(key)
      navigate('/emergency/plan', { state: { plan } })
    } catch (err) {
      setError(err.message)
      setLoadingKey(null)
    }
  }

  return (
    <div className="emergency-page">
      <div className="dashboard-heading">
        <h1>What's going on?</h1>
        <p className="muted">
          Pick the situation closest to what's happening. LifeLine will look at what's already
          stored and put together a prioritized, source-referenced plan — it doesn't diagnose,
          move money, or contact anyone for you.
        </p>
      </div>

      {error && <p className="form-error">{error}</p>}

      <div className="situation-grid">
        {SITUATIONS.map((s) => (
          <button
            key={s.key}
            className="situation-card"
            disabled={loadingKey !== null}
            onClick={() => select(s.key)}
          >
            <span className="situation-icon">{s.icon}</span>
            <span>{s.label}</span>
            {loadingKey === s.key && <span className="muted situation-loading">Building your plan…</span>}
          </button>
        ))}
      </div>
    </div>
  )
}
