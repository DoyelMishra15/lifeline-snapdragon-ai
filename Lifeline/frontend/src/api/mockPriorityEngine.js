// Mirrors backend/lib/priority_engine.py exactly (same thresholds,
// same reasoning strings) so the mock-mode demo and the real Lambda
// behave identically. Not the source of truth — backend/lib is —
// this exists only so the app works without a deployed API.

const HIGH_STAKES_TYPES = new Set(['identity', 'passport', 'insurance', 'medical', 'legal'])
const URGENT_DAYS = 14
const ATTENTION_DAYS = 30
const UPCOMING_DAYS = 90
const LOW_CONFIDENCE_THRESHOLD = 0.6

function daysUntil(dateStr) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = new Date(dateStr + 'T00:00:00')
  return Math.round((target - today) / 86400000)
}

export function classifyItem({ expiryDate, documentType, hasActions, confidence }) {
  if (confidence != null && confidence < LOW_CONFIDENCE_THRESHOLD) {
    return {
      level: 'needs_review',
      days_remaining: null,
      reason: `Extraction confidence is low (${Math.round(confidence * 100)}%); please verify this document manually.`,
      requires_action: true,
    }
  }
  if (!expiryDate) {
    return { level: 'no_action', days_remaining: null, reason: 'No dated deadline was found on this document.', requires_action: false }
  }

  const days = daysUntil(expiryDate)
  const highStakes = HIGH_STAKES_TYPES.has(documentType)

  if (days < 0) {
    return {
      level: 'urgent',
      days_remaining: days,
      reason: `This already expired ${Math.abs(days)} day(s) ago and needs immediate attention.`,
      requires_action: true,
    }
  }

  const urgentCutoff = URGENT_DAYS + (highStakes ? 7 : 0)
  const attentionCutoff = ATTENTION_DAYS + (highStakes ? 14 : 0)
  const upcomingCutoff = UPCOMING_DAYS

  if (days <= urgentCutoff) {
    return {
      level: 'urgent',
      days_remaining: days,
      reason: `High attention because this expires in ${days} day(s)${hasActions ? ' and requires renewal.' : '.'}`,
      requires_action: true,
    }
  }
  if (days <= attentionCutoff) {
    return { level: 'attention_soon', days_remaining: days, reason: `Expires in ${days} days — worth planning for soon.`, requires_action: hasActions }
  }
  if (days <= upcomingCutoff) {
    return { level: 'upcoming', days_remaining: days, reason: `Expires in ${days} days — on the radar, no action needed yet.`, requires_action: false }
  }
  return { level: 'safe', days_remaining: days, reason: `Valid for ${days} more days.`, requires_action: false }
}

const ORDER = { urgent: 0, needs_review: 1, attention_soon: 2, upcoming: 3, safe: 4, no_action: 5 }

export function rankDocuments(documents) {
  const enriched = documents.map((doc) => {
    let expiry = doc.expiry_date
    if (!expiry && doc.important_dates?.length) {
      expiry = [...doc.important_dates].sort((a, b) => a.date.localeCompare(b.date))[0].date
    }
    const priority = classifyItem({
      expiryDate: expiry,
      documentType: doc.document_type || 'other',
      hasActions: !!(doc.actions && doc.actions.length),
      confidence: doc.confidence ?? 1.0,
    })
    return { ...doc, priority }
  })
  enriched.sort((a, b) => {
    const oa = ORDER[a.priority.level], ob = ORDER[b.priority.level]
    if (oa !== ob) return oa - ob
    const da = a.priority.days_remaining ?? 9999
    const db = b.priority.days_remaining ?? 9999
    return da - db
  })
  return enriched
}
