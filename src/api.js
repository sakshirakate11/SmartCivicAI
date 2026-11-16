const API_BASE = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:5000/api').replace(/\/$/, '')

async function request(path, { token, ...options } = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    })
  } catch (error) {
    throw new Error(`Could not reach the SmartCivicAI API at ${API_BASE}. Start the Flask backend and check the frontend origin settings. (${error.message})`)
  }

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : null
  if (!response.ok) {
    throw new Error(payload?.error || `API request failed with status ${response.status}.`)
  }
  return payload
}

function apiPath(path) {
  const apiRoot = API_BASE.replace(/\/api$/, '')
  return path.startsWith('/api/') ? `${apiRoot}${path}` : `${API_BASE}${path}`
}

export const api = {
  register: (details) => request('/auth/register', {
    method: 'POST',
    body: JSON.stringify(details),
  }),
  login: (credentials) => request('/auth/login', {
    method: 'POST',
    body: JSON.stringify(credentials),
  }),
  listComplaints: (token, role, filters = {}) => {
    const path = role === 'citizen'
      ? '/complaints/mine'
      : role === 'department' ? '/department/complaints' : '/complaints'
    const params = new URLSearchParams()
    if (filters.q) params.set('q', filters.q)
    if (filters.category && filters.category !== 'All categories') params.set('category', filters.category)
    if (filters.status && filters.status !== 'All statuses') params.set('status', filters.status)
    return request(`${path}${params.size ? `?${params.toString()}` : ''}`, { token })
  },
  getSummary: (token) => request('/dashboard/summary', { token }),
  listCitizens: (token) => request('/admin/citizens', { token }),
  submitComplaint: async (token, complaint) => {
    const form = new FormData()
    for (const key of ['title', 'category', 'description', 'location']) form.set(key, complaint[key])
    if (complaint.latitude) form.set('latitude', complaint.latitude)
    if (complaint.longitude) form.set('longitude', complaint.longitude)
    if (complaint.image?.data) {
      const image = await awaitDataUrlBlob(complaint.image.data)
      form.set('image', image, complaint.image.name)
    }
    return request('/complaints', { method: 'POST', token, body: form })
  },
  updateComplaint: (token, complaintId, updates) => request(`/complaints/${encodeURIComponent(complaintId)}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(updates),
  }),
  updateDepartmentComplaint: (token, complaintId, updates) => request(`/department/complaints/${encodeURIComponent(complaintId)}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(updates),
  }),
  getComplaintHistory: (token, complaintId) => request(`/complaints/${encodeURIComponent(complaintId)}/history`, { token }),
  getComplaintInsights: (token, complaintId) => request(`/complaints/${encodeURIComponent(complaintId)}/insights`, { token }),
  submitFeedback: (token, complaintId, feedback) => request(`/complaints/${encodeURIComponent(complaintId)}/feedback`, {
    method: 'POST',
    token,
    body: JSON.stringify(feedback),
  }),
  getNotificationPreferences: (token) => request('/account/notification-preferences', { token }),
  updateNotificationPreferences: (token, preferences) => request('/account/notification-preferences', {
    method: 'PATCH',
    token,
    body: JSON.stringify(preferences),
  }),
  getMunicipalAnalytics: (token) => request('/municipal/analytics', { token }),
  getNotificationDeliveries: (token) => request('/admin/notification-deliveries', { token }),
  getMlMetrics: (token) => request('/admin/ml-metrics', { token }),
  getCategoryMappings: (token) => request('/municipal/category-mappings', { token }),
  updateCategoryMapping: (token, mapping) => request('/municipal/category-mappings', {
    method: 'PATCH',
    token,
    body: JSON.stringify(mapping),
  }),
  getVerifiedDataset: (token) => request('/municipal/ml-dataset', { token }),
  addVerifiedExample: (token, example) => request('/municipal/ml-dataset', {
    method: 'POST',
    token,
    body: JSON.stringify(example),
  }),
  updateVerifiedExample: (token, id, example) => request(`/municipal/ml-dataset/${id}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(example),
  }),
  deleteVerifiedExample: (token, id) => request(`/municipal/ml-dataset/${id}`, {
    method: 'DELETE',
    token,
  }),
  retryNotificationDelivery: (token, deliveryId) => request(`/admin/notification-deliveries/${deliveryId}/retry`, {
    method: 'POST',
    token,
    body: JSON.stringify({}),
  }),
  listNotifications: (token) => request('/notifications', { token }),
  markNotificationRead: (token, notificationId) => request(`/notifications/${notificationId}/read`, {
    method: 'PATCH',
    token,
    body: JSON.stringify({}),
  }),
  importLegacyComplaints: (token, complaints) => request('/complaints/import', {
    method: 'POST',
    token,
    body: JSON.stringify({ complaints }),
  }),
  imageUrl: apiPath,
}

async function awaitDataUrlBlob(dataUrl) {
  const response = await fetch(dataUrl)
  return response.blob()
}

export function getLegacyBackup() {
  try {
    const raw = window.localStorage.getItem('smartcivic.complaints.v1')
    if (!raw) return { complaints: [], error: '' }
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) {
      return { complaints: [], error: 'The saved browser backup is not a complaint list and was left unchanged.' }
    }
    return { complaints: parsed, error: '' }
  } catch (error) {
    return { complaints: [], error: `The browser backup could not be read and was left unchanged. (${error.message})` }
  }
}

export function downloadLegacyBackup() {
  const backup = getLegacyBackup()
  if (backup.error) throw new Error(backup.error)
  if (!backup.complaints.length) throw new Error('No browser-local complaint records were found to export.')
  const blob = new Blob([JSON.stringify({
    format: 'smartcivic-browser-backup-v1',
    exported_at: new Date().toISOString(),
    complaints: backup.complaints,
  }, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `smartcivic-complaints-${new Date().toISOString().slice(0, 10)}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}
