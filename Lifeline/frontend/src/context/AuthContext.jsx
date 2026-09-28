import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { MOCK_MODE, LOCAL_MODE, localSignup, localLogin } from '../api/client'
import { getLocalSession, setLocalSession, clearLocalSession } from '../api/localAuthToken'

const AuthContext = createContext(null)

const MOCK_KEY = 'lifeline_mock_user'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [amplifyAuth, setAmplifyAuth] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function init() {
      if (MOCK_MODE) {
        const stored = localStorage.getItem(MOCK_KEY)
        if (!cancelled) {
          setUser(stored ? JSON.parse(stored) : null)
          setLoading(false)
        }
        return
      }
      if (LOCAL_MODE) {
        const session = getLocalSession()
        if (!cancelled) {
          setUser(session ? { email: session.email, id: session.id } : null)
          setLoading(false)
        }
        return
      }
      const auth = await import('aws-amplify/auth')
      if (cancelled) return
      setAmplifyAuth(auth)
      try {
        const current = await auth.getCurrentUser()
        setUser({ email: current.signInDetails?.loginId, id: current.userId })
      } catch {
        setUser(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    init()
    return () => { cancelled = true }
  }, [])

  const signUp = useCallback(async (email, password) => {
    if (MOCK_MODE) {
      const mockUser = { email, id: `mock-${email}` }
      localStorage.setItem(MOCK_KEY, JSON.stringify(mockUser))
      setUser(mockUser)
      return { needsConfirmation: false }
    }
    if (LOCAL_MODE) {
      // Real signup against backend/handlers/local_auth.py — creates an
      // actual user record (see backend/lib/local_auth_store.py) and
      // signs the caller straight in, since there's no email service in
      // Codespaces to send a confirmation code through.
      const result = await localSignup(email, password)
      setLocalSession({ email: result.email, id: result.user_id, token: result.id_token })
      setUser({ email: result.email, id: result.user_id })
      return { needsConfirmation: false }
    }
    await amplifyAuth.signUp({ username: email, password, options: { userAttributes: { email } } })
    return { needsConfirmation: true }
  }, [amplifyAuth])

  const confirmSignUp = useCallback(async (email, code) => {
    if (MOCK_MODE || LOCAL_MODE) return // local signup skips confirmation entirely — see signUp above
    await amplifyAuth.confirmSignUp({ username: email, confirmationCode: code })
  }, [amplifyAuth])

  const signIn = useCallback(async (email, password) => {
    if (MOCK_MODE) {
      const mockUser = { email, id: `mock-${email}` }
      localStorage.setItem(MOCK_KEY, JSON.stringify(mockUser))
      setUser(mockUser)
      return
    }
    if (LOCAL_MODE) {
      const result = await localLogin(email, password)
      setLocalSession({ email: result.email, id: result.user_id, token: result.id_token })
      setUser({ email: result.email, id: result.user_id })
      return
    }
    await amplifyAuth.signIn({ username: email, password })
    const current = await amplifyAuth.getCurrentUser()
    setUser({ email: current.signInDetails?.loginId, id: current.userId })
  }, [amplifyAuth])

  const signOut = useCallback(async () => {
    if (MOCK_MODE) {
      localStorage.removeItem(MOCK_KEY)
      setUser(null)
      return
    }
    if (LOCAL_MODE) {
      clearLocalSession()
      setUser(null)
      return
    }
    await amplifyAuth.signOut()
    setUser(null)
  }, [amplifyAuth])

  return (
    <AuthContext.Provider
      value={{ user, loading, signUp, confirmSignUp, signIn, signOut, mockMode: MOCK_MODE, localMode: LOCAL_MODE }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
