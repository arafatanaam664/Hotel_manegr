import { api } from './api'

export type ProductCatalog = {
  modules: Record<string, { name_ar: string; required: boolean }>
  features: Record<string, string>
  dependencies: Record<string, string[]>
  deployment_modes: string[]
  property_types: string[]
}

export type ProductConfig = {
  tenant_id: string
  deployment_mode: 'LOCAL' | 'CLOUD' | 'HYBRID'
  property_type: string
  setup_state: 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED'
  modules_enabled: string[]
  feature_flags: Record<string, boolean>
  configured_by: string | null
  installer_identity: string
  completed_at: string | null
  installation_locked_at: string | null
  is_locked: boolean
  installer_only: boolean
  version: number
  updated_at: string | null
}

export type ProductConfigInput = {
  deployment_mode: ProductConfig['deployment_mode']
  property_type: string
  modules_enabled: string[]
  feature_flags: Record<string, boolean>
  multi_branch: boolean
  complete: boolean
  installer_identity: string
}

export const setupApi = {
  catalog: () => api<ProductCatalog>('/api/setup/catalog'),
  product: () => api<ProductConfig>('/api/setup/product'),
  saveProduct: (body: ProductConfigInput, installerToken: string) => api<ProductConfig>('/api/setup/product', {
    method: 'PUT',
    headers: { 'X-Installer-Token': installerToken },
    body: JSON.stringify(body),
  }),
}
