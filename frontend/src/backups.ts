import { api } from './api'

export type Backup = {
  id: string
  file_name: string
  storage_kind: string
  size_bytes: number
  sha256: string
  status: string
  created_at: string
  verified?: boolean
}

export const backupApi = {
  list: () => api<Backup[]>('/api/backups'),
  create: () => api<Backup>('/api/backups', { method: 'POST' }),
  verify: (id: string) => api<Backup>(`/api/backups/${id}/verify`, { method: 'POST' }),
}
