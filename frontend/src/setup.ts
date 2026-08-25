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
  completed_at: string | null
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
}

export const setupApi = {
  catalog: () => api<ProductCatalog>('/api/setup/catalog'),
  product: () => api<ProductConfig>('/api/setup/product'),
  saveProduct: (body: ProductConfigInput) => api<ProductConfig>('/api/setup/product', {
    method: 'PUT',
    body: JSON.stringify(body),
  }),
}
