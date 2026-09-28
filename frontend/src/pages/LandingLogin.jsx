import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './landing.css'

export default function LandingLogin() {
  const { signIn, signUp, confirmSignUp } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState('signin') // signin | signup | confirm
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'signin') {
        await signIn(email, password)
        navigate('/dashboard')
      } else if (mode === 'signup') {
        const result = await signUp(email, password)
        if (result.needsConfirmation) setMode('confirm')
        else navigate('/dashboard')
      } else if (mode === 'confirm') {
        await confirmSignUp(email, code)
        await signIn(email, password)
        navigate('/dashboard')
      }
    } catch (err) {
      setError(err.message || 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="landing">
      <section className="landing-hero">
        <div className="container landing-hero-inner">
          <p className="landing-eyebrow">Personal information &amp; emergency continuity</p>
          <h1 className="landing-headline">
            Everything important, in one place —<br />ready the moment something goes wrong.
          </h1>
          <p className="landing-sub">
            LifeLine collects your documents, understands what's in them, and tells you what
            needs attention before it becomes a problem. And if something does go wrong, it
            already knows where to look.
          </p>
          <div className="landing-pipeline">
            <span>Collect</span><span className="arrow">→</span>
            <span>Understand</span><span className="arrow">→</span>
            <span>Prioritize</span><span className="arrow">→</span>
            <span>Respond</span>
          </div>
        </div>
      </section>

      <section className="container landing-auth-section">
        <div className="panel landing-auth-panel">
          <h2>{mode === 'signin' ? 'Sign in' : mode === 'signup' ? 'Create your account' : 'Check your email'}</h2>

          {mode === 'confirm' ? (
            <form onSubmit={handleSubmit} className="auth-form">
              <p className="landing-sub" style={{ fontSize: '0.9rem' }}>
                Enter the confirmation code we sent to {email}.
              </p>
              <input placeholder="Confirmation code" value={code} onChange={(e) => setCode(e.target.value)} required />
              {error && <p className="form-error">{error}</p>}
              <button className="btn btn-signal" disabled={busy}>{busy ? 'Confirming…' : 'Confirm and sign in'}</button>
            </form>
          ) : (
            <form onSubmit={handleSubmit} className="auth-form">
              <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
              {error && <p className="form-error">{error}</p>}
              <button className="btn btn-signal" disabled={busy}>
                {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
              </button>
            </form>
          )}

          {mode !== 'confirm' && (
            <button className="link-btn" onClick={() => { setMode(mode === 'signin' ? 'signup' : 'signin'); setError('') }}>
              {mode === 'signin' ? "New to LifeLine? Create an account" : 'Already have an account? Sign in'}
            </button>
          )}

        </div>
      </section>
    </div>
  )
}
