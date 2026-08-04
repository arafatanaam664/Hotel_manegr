import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Accounts from './pages/Accounts'
import Journals from './pages/Journals'
import JournalNew from './pages/JournalNew'
import JournalDetail from './pages/JournalDetail'
import TrialBalance from './pages/TrialBalance'
import Ledger from './pages/Ledger'
import Audit from './pages/Audit'

export default function App() {
  const { session } = useAuth()
  if (!session) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="journals" element={<Journals />} />
        <Route path="journals/new" element={<JournalNew />} />
        <Route path="journals/:id" element={<JournalDetail />} />
        <Route path="trial-balance" element={<TrialBalance />} />
        <Route path="ledger" element={<Ledger />} />
        <Route path="audit" element={<Audit />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
      <Route path="/login" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
