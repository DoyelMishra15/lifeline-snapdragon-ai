const LEVEL_META = {
  urgent: { label: 'Urgent', dot: '🔴', color: 'var(--urgent)', bg: 'var(--urgent-soft)' },
  attention_soon: { label: 'Attention soon', dot: '🟠', color: 'var(--soon)', bg: 'var(--soon-soft)' },
  needs_review: { label: 'Needs review', dot: '🟣', color: 'var(--review)', bg: 'var(--review-soft)' },
  upcoming: { label: 'Upcoming', dot: '🔵', color: 'var(--upcoming)', bg: 'var(--upcoming-soft)' },
  safe: { label: 'Safe', dot: '🟢', color: 'var(--signal)', bg: 'var(--signal-soft)' },
  no_action: { label: 'No action needed', dot: '⚪', color: 'var(--ink-soft)', bg: 'var(--line)' },
}

export default function PriorityBadge({ level, compact = false }) {
  const meta = LEVEL_META[level] || LEVEL_META.no_action
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.35rem',
        fontSize: compact ? '0.72rem' : '0.8rem',
        fontWeight: 600,
        color: meta.color,
        background: meta.bg,
        padding: compact ? '0.15rem 0.5rem' : '0.25rem 0.65rem',
        borderRadius: '999px',
        whiteSpace: 'nowrap',
      }}
    >
      {meta.dot} {meta.label}
    </span>
  )
}

export { LEVEL_META }
