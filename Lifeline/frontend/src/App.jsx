import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import LandingLogin from './pages/LandingLogin'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import DocumentDetail from './pages/DocumentDetail'
import Attention from './pages/Attention'
import Emergency from './pages/Emergency'
import ActionPlan from './pages/ActionPlan'
import Settings from './pages/Settings'

function Protected({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="container" style={{ paddingTop: '4rem' }}>Loading…</div>
  if (!user) return <Navigate to="/" replace />
  return children
}

export default function App() {
  const { user } = useAuth()

  return (
    <Routes>
      <Route path="/" element={user ? <Navigate to="/dashboard" replace /> : <LandingLogin />} />
      <Route element={<Layout />}>
        <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
        <Route path="/documents" element={<Protected><Documents /></Protected>} />
        <Route path="/documents/:documentId" element={<Protected><DocumentDetail /></Protected>} />
        <Route path="/attention" element={<Protected><Attention /></Protected>} />
        <Route path="/emergency" element={<Protected><Emergency /></Protected>} />
        <Route path="/emergency/plan" element={<Protected><ActionPlan /></Protected>} />
        <Route path="/settings" element={<Protected><Settings /></Protected>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
