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
import FrontDesk from './pages/FrontDesk'
import Reservations from './pages/Reservations'
import ReservationDetail from './pages/ReservationDetail'
import NightAudit from './pages/NightAudit'
import HotelRooms from './pages/HotelRooms'
import Guests from './pages/Guests'
import PosSale from './pages/PosSale'
import PosOrders from './pages/PosOrders'
import PosShifts from './pages/PosShifts'
import PosCatalog from './pages/PosCatalog'
import PosReports from './pages/PosReports'
import InvCatalog from './pages/InvCatalog'
import InvPurchasing from './pages/InvPurchasing'
import InvOperations from './pages/InvOperations'
import InvReports from './pages/InvReports'
import HrPeople from './pages/HrPeople'
import HrTime from './pages/HrTime'
import HrPayroll from './pages/HrPayroll'
import HrReports from './pages/HrReports'
import FinAssets from './pages/FinAssets'
import FinStatements from './pages/FinStatements'
import FinClose from './pages/FinClose'
import LicenseStatus from './pages/LicenseStatus'
import SyncCenter from './pages/SyncCenter'
import UsersPage from './pages/Users'
import Police from './pages/Police'
import ProductSetup from './pages/ProductSetup'
import Backups from './pages/Backups'
import HotelReports from './pages/HotelReports'

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
        <Route path="front-desk" element={<FrontDesk />} />
        <Route path="reservations" element={<Reservations />} />
        <Route path="reservations/:id" element={<ReservationDetail />} />
        <Route path="guests" element={<Guests />} />
        <Route path="night-audit" element={<NightAudit />} />
        <Route path="rooms" element={<HotelRooms />} />
        <Route path="pos" element={<PosSale />} />
        <Route path="pos/orders" element={<PosOrders />} />
        <Route path="pos/shifts" element={<PosShifts />} />
        <Route path="pos/catalog" element={<PosCatalog />} />
        <Route path="pos/reports" element={<PosReports />} />
        <Route path="inv/catalog" element={<InvCatalog />} />
        <Route path="inv/purchasing" element={<InvPurchasing />} />
        <Route path="inv/operations" element={<InvOperations />} />
        <Route path="inv/reports" element={<InvReports />} />
        <Route path="hr/people" element={<HrPeople />} />
        <Route path="hr/time" element={<HrTime />} />
        <Route path="hr/payroll" element={<HrPayroll />} />
        <Route path="hr/reports" element={<HrReports />} />
        <Route path="fin/assets" element={<FinAssets />} />
        <Route path="fin/statements" element={<FinStatements />} />
        <Route path="fin/close" element={<FinClose />} />
          <Route path="license" element={<LicenseStatus />} />
          <Route path="sync" element={<SyncCenter />} />
          <Route path="users" element={<UsersPage />} />
        <Route path="setup" element={<ProductSetup />} />
        <Route path="backups" element={<Backups />} />
        <Route path="hotel-reports" element={<HotelReports />} />
          <Route path="police" element={<Police />} />
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
