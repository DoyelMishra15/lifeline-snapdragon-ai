import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './layout.css'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/documents', label: 'Documents' },
  { to: '/attention', label: 'Attention' },
  { to: '/settings', label: 'Settings' },
]

export default function Layout() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="container shell-header-inner">
          <div className="brand" onClick={() => navigate('/dashboard')}>
            <span className="brand-mark">🛟</span>
            <span className="brand-name">LifeLine</span>
          </div>
          <nav className="shell-nav">
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={({ isActive }) => `shell-nav-link${isActive ? ' active' : ''}`}>
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="shell-header-actions">
            <span className="shell-user">{user?.email}</span>
            <button className="btn btn-secondary" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </header>

      <main className="container shell-main">
        <Outlet />
      </main>

      <button className="emergency-fab" onClick={() => navigate('/emergency')}>
        I have a problem
      </button>
    </div>
  )
}
