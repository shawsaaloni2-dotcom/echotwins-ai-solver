// ═══════════════════════════════════════════════════════════
//  EchoTwins AI — Central Client Config (NO SECRETS HERE)
//  Copy this to config.js and fill in public values only.
//  NEVER put DATABASE_URL, service_role, or any server secret here.
// ═══════════════════════════════════════════════════════════

const ECHOTWINS_CONFIG = {

  // ── 1. META MODEL API (Muse) ──────────────────────────────
  // Keys are stored in the user's browser localStorage, not here.
  get META_API_KEY() {
    return localStorage.getItem('et_meta_key') || '';
  },
  META_MODEL:    'muse-wonder',
  META_ENDPOINT: 'https://api.meta.com/v1/chat/completions',

  // ── 2. GOOGLE GEMINI API ──────────────────────────────────
  get GEMINI_API_KEY() {
    return localStorage.getItem('et_gemini_key') || '';
  },
  GEMINI_MODEL:    'gemini-2.0-flash',
  GEMINI_ENDPOINT: 'https://generativelanguage.googleapis.com/v1beta/models',

  // ── 3. AI PROVIDER PRIORITY ───────────────────────────────
  get AI_PROVIDER() {
    return localStorage.getItem('et_ai_provider') || 'gemini';
  },

  // ── STATUS FLAGS ──────────────────────────────────────────
  get META_READY()   { return Boolean(this.META_API_KEY   && this.META_API_KEY.trim().length   > 5); },
  get GEMINI_READY() { return Boolean(this.GEMINI_API_KEY && this.GEMINI_API_KEY.trim().length > 5); },

  get ACTIVE_AI() {
    if (this.AI_PROVIDER === 'meta'   && this.META_READY)   return 'meta';
    if (this.AI_PROVIDER === 'gemini' && this.GEMINI_READY) return 'gemini';
    if (this.AI_PROVIDER === 'auto') {
      if (this.META_READY)   return 'meta';
      if (this.GEMINI_READY) return 'gemini';
    }
    if (this.GEMINI_READY) return 'gemini';
    if (this.META_READY)   return 'meta';
    return 'demo';
  },

  saveKeys({ geminiKey, metaKey, provider } = {}) {
    if (geminiKey !== undefined) {
      if (geminiKey) localStorage.setItem('et_gemini_key', geminiKey.trim());
      else           localStorage.removeItem('et_gemini_key');
    }
    if (metaKey !== undefined) {
      if (metaKey) localStorage.setItem('et_meta_key', metaKey.trim());
      else         localStorage.removeItem('et_meta_key');
    }
    if (provider) localStorage.setItem('et_ai_provider', provider);
  }
};

