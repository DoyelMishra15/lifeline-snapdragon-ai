// Local-mode session storage (Codespaces / SAM-local + LocalStack —
// see docs/local-development.md). Holds the JWT issued by
// backend/handlers/local_auth.py after a real signup/login call, plus
// the user's id/email, so AuthContext.jsx (session state) and
// api/client.js (Authorization header) share one source of truth
// instead of each reading/writing localStorage themselves.
//
// Only used when VITE_LOCAL_MODE=true. Not used for the mock/demo
// path (no backend at all) or the real-Cognito path (Amplify manages
// its own session storage).
const STORAGE_KEY = 'lifeline_local_session'

export function getLocalSession() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setLocalSession(session) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function clearLocalSession() {
  localStorage.removeItem(STORAGE_KEY)
}
