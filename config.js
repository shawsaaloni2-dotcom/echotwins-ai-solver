// ═══════════════════════════════════════════════════════════
//  EchoTwins AI — Central API Configuration
//  Edit this file to add your API keys or save them directly
//  via the Settings UI in the app.
// ═══════════════════════════════════════════════════════════

const ECHOTWINS_CONFIG = {

  // ── 1. META MODEL API (Muse) ─────────────────────────────
  // Platform : https://api.meta.com  (left sidebar → API keys)
  // Models   : muse-wonder, muse-spark-open
  get META_API_KEY() {
    return localStorage.getItem('et_meta_key') || "PASTE_YOUR_META_API_KEY_HERE";
  },
  META_MODEL:        "muse-wonder",
  META_ENDPOINT:     "https://api.meta.com/v1/chat/completions",

  // ── 2. GOOGLE GEMINI API ─────────────────────────────────
  // Platform : https://aistudio.google.com/app/apikey
  // Free tier: 60 req/min — no credit card needed
  get GEMINI_API_KEY() {
    return localStorage.getItem('et_gemini_key') || "PASTE_YOUR_GEMINI_API_KEY_HERE";
  },
  GEMINI_MODEL:      "gemini-2.0-flash",
  GEMINI_ENDPOINT:   "https://generativelanguage.googleapis.com/v1beta/models",

  // ── 3. AI PROVIDER PRIORITY ──────────────────────────────
  // Which AI to use first? "meta" | "gemini" | "auto"
  get AI_PROVIDER() {
    return localStorage.getItem('et_ai_provider') || "gemini";
  },

  // ── 4. FIREBASE (Auth + Firestore) ───────────────────────
  // Platform : https://console.firebase.google.com
  FIREBASE: {
    apiKey:            "PASTE_YOUR_FIREBASE_API_KEY_HERE",
    authDomain:        "YOUR_PROJECT_ID.firebaseapp.com",
    projectId:         "YOUR_PROJECT_ID",
    storageBucket:     "YOUR_PROJECT_ID.appspot.com",
    messagingSenderId: "YOUR_SENDER_ID",
    appId:             "YOUR_APP_ID"
  },

  // ── STATUS FLAGS (auto-detected) ─────────────────────────
  get META_READY()     { return Boolean(this.META_API_KEY && this.META_API_KEY !== "PASTE_YOUR_META_API_KEY_HERE" && this.META_API_KEY.trim().length > 5); },
  get GEMINI_READY()   { return Boolean(this.GEMINI_API_KEY && this.GEMINI_API_KEY !== "PASTE_YOUR_GEMINI_API_KEY_HERE" && this.GEMINI_API_KEY.trim().length > 5); },
  get FIREBASE_READY() { return Boolean(this.FIREBASE.apiKey && this.FIREBASE.apiKey !== "PASTE_YOUR_FIREBASE_API_KEY_HERE" && this.FIREBASE.apiKey.trim().length > 5); },

  // Which AI provider is actually active right now?
  get ACTIVE_AI() {
    if (this.AI_PROVIDER === "meta"   && this.META_READY)   return "meta";
    if (this.AI_PROVIDER === "gemini" && this.GEMINI_READY) return "gemini";
    if (this.AI_PROVIDER === "auto") {
      if (this.META_READY)   return "meta";
      if (this.GEMINI_READY) return "gemini";
    }
    if (this.GEMINI_READY) return "gemini";
    if (this.META_READY)   return "meta";
    return "demo";
  },

  // Helper to save keys dynamically
  saveKeys({ geminiKey, metaKey, provider }) {
    if (geminiKey !== undefined) {
      if (geminiKey) localStorage.setItem('et_gemini_key', geminiKey.trim());
      else localStorage.removeItem('et_gemini_key');
    }
    if (metaKey !== undefined) {
      if (metaKey) localStorage.setItem('et_meta_key', metaKey.trim());
      else localStorage.removeItem('et_meta_key');
    }
    if (provider) {
      localStorage.setItem('et_ai_provider', provider);
    }
  }
};
