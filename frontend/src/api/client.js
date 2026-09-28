// LifeLine API client.
//
// Three modes, chosen by environment variables alone — nothing else in
// this file branches on "which environment am I in":
//   - MOCK_MODE (no VITE_API_BASE_URL): in-memory demo data, no backend.
//   - LOCAL_MODE (VITE_API_BASE_URL set + VITE_LOCAL_MODE=true): talks
//     to the real backend (SAM local + LocalStack, via Vite's /api
//     proxy — see vite.config.js) using a local JWT from
//     backend/handlers/local_auth.py instead of Cognito.
//   - Real AWS (VITE_API_BASE_URL set, VITE_LOCAL_MODE unset): talks to
//     a deployed API Gateway using a real Cognito session (Amplify).
import { getLocalSession } from './localAuthToken'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/+$/, '')
export const MOCK_MODE = !API_BASE
export const LOCAL_MODE = !MOCK_MODE && import.meta.env.VITE_LOCAL_MODE === 'true'

if (MOCK_MODE && import.meta.env.PROD) {
  // Loud, once, in the browser console only — never silently ships a
  // production build that looks live but is actually serving demo
  // data. Fix: set VITE_API_BASE_URL (and the Cognito vars) before
  // building for deployment; see .env.example.
  // eslint-disable-next-line no-console
  console.warn(
    '[LifeLine] VITE_API_BASE_URL is not set in this production build — ' +
    'the app is running on local demo/mock data, not the real backend.'
  )
}

async function authHeader() {
  if (MOCK_MODE) return {}
  if (LOCAL_MODE) {
    const session = getLocalSession()
    return session?.token ? { Authorization: `Bearer ${session.token}` } : {}
  }
  try {
    const { fetchAuthSession } = await import('aws-amplify/auth')
    const session = await fetchAuthSession()
    const token = session.tokens?.idToken?.toString()
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(await authHeader()), ...options.headers }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Request failed (${res.status})`)
  }
  return res.json()
}

// ---------------------------------------------------------------
// Local auth (LOCAL_MODE only) — calls the real backend/handlers/
// local_auth.py endpoints. Not used in MOCK_MODE (no backend to call)
// or the real-AWS path (Amplify/Cognito instead — see AuthContext.jsx).
// ---------------------------------------------------------------
export async function localSignup(email, password) {
  return request('/auth/signup', { method: 'POST', body: JSON.stringify({ email, password }) })
}

export async function localLogin(email, password) {
  return request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '')
    reader.onerror = () => reject(new Error('Could not read the file'))
    reader.readAsDataURL(file)
  })
}

// ---------------------------------------------------------------
// Mock backend — mirrors backend/lib/priority_engine.py and
// backend/handlers/*.py exactly so switching to a real API changes
// nothing about how the UI consumes the data.
// ---------------------------------------------------------------
import { rankDocuments, classifyItem } from './mockPriorityEngine'
import { mockSeedDocuments, mockExtract, mockEmergencyPlan } from './mockData'

const wait = (ms) => new Promise((r) => setTimeout(r, ms))
let _mockDocs = null
function seedIfNeeded() {
  if (!_mockDocs) _mockDocs = JSON.parse(JSON.stringify(mockSeedDocuments))
}

export async function listDocuments() {
  if (!MOCK_MODE) return request('/documents')
  seedIfNeeded()
  await wait(350)
  const ranked = rankDocuments(_mockDocs)
  // Mirrors the shape backend/handlers/documents.py::list_handler
  // returns, including recent_events — in the real deployment those
  // come from the EventBridge-driven sweep (handlers/reminders.py);
  // here they're derived client-side so the mock demo shows the same
  // "recent activity" surface without pretending to be a real sweep.
  const recent_events = ranked
    .filter((d) => d.expiry_date)
    .map((d) => ({
      document_id: d.document_id,
      title: d.title,
      priority_level: d.priority.level,
      reason: d.priority.reason,
      created_at: d.updated_at || d.created_at || '',
    }))
  return { documents: ranked, conflicts: [], recent_events }
}

export async function getDocument(documentId) {
  if (!MOCK_MODE) return request(`/documents/${documentId}`)
  seedIfNeeded()
  await wait(250)
  const doc = _mockDocs.find((d) => d.document_id === documentId)
  if (!doc) throw new Error('Document not found')
  return { ...rankDocuments([doc])[0], source_url: doc.source_url || null }
}

export async function requestUploadUrl(file) {
  if (LOCAL_MODE) {
    // A presigned URL generated inside a SAM-local Lambda container
    // would embed LocalStack's internal Docker-network hostname,
    // which the browser can never reach — so local mode sends the
    // file inline instead (see backend/handlers/upload.py) and skips
    // the presigned-PUT step entirely (upload_url comes back null).
    const file_content_base64 = await fileToBase64(file)
    return request('/documents/upload-url', {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name, content_type: file.type, size_bytes: file.size, file_content_base64,
      }),
    })
  }
  if (!MOCK_MODE) {
    return request('/documents/upload-url', {
      method: 'POST',
      body: JSON.stringify({ filename: file.name, content_type: file.type, size_bytes: file.size }),
    })
  }
  seedIfNeeded()
  await wait(200)
  const document_id = `mock-${Date.now()}`
  _mockDocs.push({
    document_id,
    title: file.name,
    document_type: 'other',
    status: 'uploaded',
    filename: file.name,
    confidence: null,
  })
  return { document_id, upload_url: null, s3_key: `users/mock/documents/${document_id}/${file.name}` }
}

export async function uploadToPresignedUrl(uploadUrl, file) {
  if (!uploadUrl) return // LOCAL_MODE (and mock, sometimes): file was already stored server-side
  if (!MOCK_MODE) {
    const res = await fetch(uploadUrl, { method: 'PUT', body: file, headers: { 'Content-Type': file.type } })
    if (!res.ok) throw new Error('Upload to storage failed')
    return
  }
  await wait(400) // simulate the S3 PUT
}

export async function processDocument(documentId, filenameHint) {
  if (!MOCK_MODE) return request(`/documents/${documentId}/process`, { method: 'POST' })
  seedIfNeeded()
  await wait(1400) // simulate Bedrock extraction latency
  const idx = _mockDocs.findIndex((d) => d.document_id === documentId)
  const extracted = mockExtract(filenameHint || _mockDocs[idx]?.filename || '')
  _mockDocs[idx] = { ..._mockDocs[idx], ...extracted, status: 'processed', document_id: documentId }
  return { document_id: documentId, status: 'processed', extraction: extracted }
}

export async function getProfile() {
  if (!MOCK_MODE) return request('/profile')
  await wait(150)
  return JSON.parse(localStorage.getItem('lifeline_mock_profile') || '{}')
}

export async function putProfile(profile) {
  if (!MOCK_MODE) return request('/profile', { method: 'PUT', body: JSON.stringify(profile) })
  await wait(150)
  localStorage.setItem('lifeline_mock_profile', JSON.stringify(profile))
  return profile
}

export async function generateEmergencyPlan(situationKey) {
  if (!MOCK_MODE) return request('/emergency/plan', { method: 'POST', body: JSON.stringify({ situation: situationKey }) })
  seedIfNeeded()
  await wait(1600)
  return mockEmergencyPlan(situationKey, _mockDocs)
}

export async function triggerReminderSweep() {
  // Calls the exact same backend/handlers/reminders.py logic
  // EventBridge's daily schedule invokes in a real deployment — see
  // infrastructure/template.yaml's ReminderSweepFunction. A
  // `rate(1 day)` schedule can't be watched firing live, so this
  // on-demand trigger is how the sweep is actually demoed.
  if (!MOCK_MODE) return request('/reminders/sweep', { method: 'POST' })
  seedIfNeeded()
  await wait(600)
  return { statusCode: 200, body: `Swept ${_mockDocs.length} document(s) (demo data).` }
}

export { classifyItem }
