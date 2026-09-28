function isoDaysFromNow(n) {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

export const mockSeedDocuments = [
  {
    document_id: 'seed-insurance',
    status: 'processed',
    document_type: 'insurance',
    title: 'Health Insurance Policy',
    provider: 'Apollo Munich',
    filename: 'health_insurance_policy.pdf',
    expiry_date: isoDaysFromNow(12),
    important_dates: [{ date: isoDaysFromNow(12), type: 'expiry', description: 'Policy expires' }],
    amount: '₹12,500 / year',
    actions: ['Renew before expiry', 'Compare add-on riders'],
    relevant_entities: ['Apollo Munich Health Insurance'],
    warnings: [],
    confidence: 0.93,
    source_url: null,
  },
  {
    document_id: 'seed-warranty',
    status: 'processed',
    document_type: 'warranty',
    title: 'Laptop Warranty — ThinkPad X1',
    provider: 'Lenovo',
    filename: 'laptop_warranty.pdf',
    expiry_date: isoDaysFromNow(29),
    important_dates: [{ date: isoDaysFromNow(29), type: 'expiry', description: 'Warranty coverage ends' }],
    amount: null,
    actions: ['Consider extended warranty'],
    relevant_entities: ['Lenovo Care'],
    warnings: [],
    confidence: 0.88,
    source_url: null,
  },
  {
    document_id: 'seed-passport',
    status: 'processed',
    document_type: 'passport',
    title: 'Passport',
    provider: 'Government of India',
    filename: 'passport_scan.jpg',
    expiry_date: isoDaysFromNow(210),
    important_dates: [{ date: isoDaysFromNow(210), type: 'expiry', description: 'Passport expires' }],
    amount: null,
    actions: [],
    relevant_entities: [],
    warnings: [],
    confidence: 0.97,
    source_url: null,
  },
  {
    document_id: 'seed-subscription',
    status: 'processed',
    document_type: 'subscription',
    title: 'Cloud Storage Subscription',
    provider: 'Google One',
    filename: 'google_one_receipt.pdf',
    expiry_date: isoDaysFromNow(55),
    important_dates: [{ date: isoDaysFromNow(55), type: 'renewal', description: 'Auto-renews' }],
    amount: '₹650 / month',
    actions: ['Cancel or downgrade if unused'],
    relevant_entities: ['Google One'],
    warnings: [],
    confidence: 0.81,
    source_url: null,
  },
  {
    document_id: 'seed-blurry',
    status: 'needs_review',
    document_type: 'other',
    title: 'Scanned Certificate (unclear)',
    provider: null,
    filename: 'certificate_scan.jpg',
    expiry_date: null,
    important_dates: [],
    amount: null,
    actions: [],
    relevant_entities: [],
    warnings: ['Image was too blurry to confidently read the date field.'],
    confidence: 0.42,
    source_url: null,
  },
]

const EXTRACTION_TEMPLATES = [
  {
    match: /insur/i,
    build: () => ({
      document_type: 'insurance', title: 'Insurance Policy', provider: 'Detected Insurance Co.',
      expiry_date: isoDaysFromNow(18), important_dates: [{ date: isoDaysFromNow(18), type: 'expiry', description: 'Policy expires' }],
      amount: '₹9,800 / year', actions: ['Renew before expiry'], relevant_entities: [], warnings: [], confidence: 0.91,
    }),
  },
  {
    match: /passport|id|identity/i,
    build: () => ({
      document_type: 'identity', title: 'Identity Document', provider: 'Government Issued',
      expiry_date: isoDaysFromNow(400), important_dates: [{ date: isoDaysFromNow(400), type: 'expiry', description: 'Document expires' }],
      amount: null, actions: [], relevant_entities: [], warnings: [], confidence: 0.95,
    }),
  },
  {
    match: /warrant/i,
    build: () => ({
      document_type: 'warranty', title: 'Product Warranty', provider: 'Detected Manufacturer',
      expiry_date: isoDaysFromNow(60), important_dates: [{ date: isoDaysFromNow(60), type: 'expiry', description: 'Coverage ends' }],
      amount: null, actions: [], relevant_entities: [], warnings: [], confidence: 0.85,
    }),
  },
  {
    match: /bill|invoice|subscription|receipt/i,
    build: () => ({
      document_type: 'bill', title: 'Bill / Subscription', provider: 'Detected Provider',
      expiry_date: isoDaysFromNow(20), important_dates: [{ date: isoDaysFromNow(20), type: 'payment_due', description: 'Payment due' }],
      amount: '₹1,200', actions: ['Pay before due date'], relevant_entities: [], warnings: [], confidence: 0.79,
    }),
  },
]

export function mockExtract(filename) {
  for (const t of EXTRACTION_TEMPLATES) {
    if (t.match.test(filename)) return t.build()
  }
  return {
    document_type: 'other', title: filename || 'Uploaded Document', provider: null,
    expiry_date: null, important_dates: [], amount: null, actions: [],
    relevant_entities: [], warnings: ['No clear date field detected — please review.'], confidence: 0.55,
  }
}

const SITUATION_PLANS = {
  lost_wallet: {
    summary: 'Secure your identity and payment documents and know what needs replacing.',
    relevantTypes: ['identity', 'passport', 'insurance', 'financial'],
    steps: [
      { action: 'Note which identity/payment documents were in the wallet', why: 'Determines what needs replacing and where to report loss.' },
      { action: 'Check your emergency contact is reachable', why: 'They may need to help coordinate replacements.' },
      { action: 'Review stored insurance details for any card-protection cover', why: 'Some policies cover fraudulent use after a lost card.' },
      { action: 'List documents that will need reissue', why: 'Passport/ID reissue often has its own timeline — start early.' },
    ],
  },
  lost_phone: {
    summary: 'Lock down accounts tied to your phone number and preserve access to key documents.',
    relevantTypes: ['identity', 'financial'],
    steps: [
      { action: 'Ask your carrier to suspend the SIM', why: 'Prevents SIM-based account takeover.' },
      { action: 'Check which stored documents reference this phone number for 2FA', why: 'Those accounts need an alternate recovery method.' },
      { action: 'Review emergency contact details', why: 'They may need an alternate way to reach you.' },
    ],
  },
  medical_emergency: {
    summary: 'Surface the documents someone would need if they were helping you right now.',
    relevantTypes: ['medical', 'insurance', 'identity'],
    steps: [
      { action: 'Share stored health insurance details with whoever is assisting you', why: 'Needed for hospital admission and billing.' },
      { action: 'Provide your emergency contact information', why: 'Hospitals typically require a contact on file.' },
      { action: 'Have identity documents ready for admission paperwork', why: 'Required for hospital registration.' },
    ],
  },
  temporarily_unavailable: {
    summary: 'Make sure anything time-sensitive keeps moving while you are unreachable.',
    relevantTypes: ['bill', 'subscription', 'insurance'],
    steps: [
      { action: 'Review upcoming deadlines in the next 2 weeks', why: 'These will need handling before you are back.' },
      { action: 'Share access instructions with a trusted contact if needed', why: 'So nothing lapses while you are away.' },
    ],
  },
  travel_emergency: {
    summary: 'Get your identity and insurance documents in front of you fast.',
    relevantTypes: ['passport', 'identity', 'insurance'],
    steps: [
      { action: 'Pull up your passport / identity document details', why: 'Often requested by local authorities or embassies.' },
      { action: 'Check travel insurance coverage and provider contact', why: 'Needed to file a claim or request assistance.' },
      { action: 'Share your emergency contact with anyone assisting you', why: 'They may need to be reached on your behalf.' },
    ],
  },
  other: {
    summary: 'Here is what LifeLine has on file that may be relevant.',
    relevantTypes: [],
    steps: [{ action: 'Review your stored documents below', why: 'Starting point for figuring out next steps.' }],
  },
}

export function mockEmergencyPlan(situationKey, documents) {
  const plan = SITUATION_PLANS[situationKey] || SITUATION_PLANS.other
  const processed = documents.filter((d) => d.status === 'processed')
  const relevant = plan.relevantTypes.length
    ? processed.filter((d) => plan.relevantTypes.includes(d.document_type))
    : processed

  const steps = plan.steps.map((s, i) => ({
    order: i + 1,
    action: s.action,
    why: s.why,
    source_document_ids: relevant.map((d) => d.document_id),
  }))

  return {
    situation: situationKey,
    summary: plan.summary,
    steps,
    relevant_documents: relevant.map((d) => d.document_id),
    missing_information: relevant.length === 0 ? ['No relevant documents are on file yet for this situation.'] : [],
    disclaimer: 'LifeLine prepares information and next steps for you to act on. It does not diagnose medical conditions, provide treatment advice, move money, or contact anyone on your behalf.',
    document_count_considered: processed.length,
    documents_by_id: Object.fromEntries(documents.map((d) => [d.document_id, d])),
  }
}
