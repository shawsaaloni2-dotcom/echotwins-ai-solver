// ═══════════════════════════════════════════════════════════
//  EchoTwins AI — Central API Configuration
//  Edit this file to add your API keys.
//  All pages (login, dashboard, solver) load this file.
// ═══════════════════════════════════════════════════════════

const ECHOTWINS_CONFIG = {

  // ── 1. META MODEL API (Muse) ─────────────────────────────
  // Platform : https://api.meta.com  (left sidebar → API keys)
  // Models   : muse-wonder, muse-spark-open  (see your screenshot)
  // Billing  : Add a payment method on the Billing page first
  META_API_KEY:      "PASTE_YOUR_META_API_KEY_HERE",
  META_MODEL:        "muse-wonder",             // or "muse-spark-open" (free/open)
  META_ENDPOINT:     "https://api.meta.com/v1/chat/completions",

  // ── 2. GOOGLE GEMINI API ─────────────────────────────────
  // Platform : https://aistudio.google.com/app/apikey
  // Free tier: 60 req/min — no credit card needed
  GEMINI_API_KEY:    "PASTE_YOUR_GEMINI_API_KEY_HERE",
  GEMINI_MODEL:      "gemini-2.0-flash",
  GEMINI_ENDPOINT:   "https://generativelanguage.googleapis.com/v1beta/models",

  // ── 3. AI PROVIDER PRIORITY ──────────────────────────────
  // Which AI to use first? "meta" | "gemini" | "auto"
  // "auto" = use Meta if key present, fall back to Gemini, then demo
  AI_PROVIDER: "gemini",

  // ── 4. FIREBASE (Auth + Firestore) ───────────────────────
  // Platform : https://console.firebase.google.com
  // Project Settings → Your apps → Web app → SDK config
  FIREBASE: {
    apiKey:            "PASTE_YOUR_FIREBASE_API_KEY_HERE",
    authDomain:        "YOUR_PROJECT_ID.firebaseapp.com",
    projectId:         "YOUR_PROJECT_ID",
    storageBucket:     "YOUR_PROJECT_ID.appspot.com",
    messagingSenderId: "YOUR_SENDER_ID",
    appId:             "YOUR_APP_ID"
  },

  // ── STATUS FLAGS (auto-detected) ─────────────────────────
  get META_READY()     { return this.META_API_KEY     !== "PASTE_YOUR_META_API_KEY_HERE"; },
  get GEMINI_READY()   { return this.GEMINI_API_KEY   !== "PASTE_YOUR_GEMINI_API_KEY_HERE"; },
  get FIREBASE_READY() { return this.FIREBASE.apiKey  !== "PASTE_YOUR_FIREBASE_API_KEY_HERE"; },

  // Which AI provider is actually active right now?
  get ACTIVE_AI() {
    if (this.AI_PROVIDER === "meta"   && this.META_READY)   return "meta";
    if (this.AI_PROVIDER === "gemini" && this.GEMINI_READY) return "gemini";
    if (this.AI_PROVIDER === "auto") {
      if (this.META_READY)   return "meta";
      if (this.GEMINI_READY) return "gemini";
    }
    return "demo";
  }
};

Object.freeze(ECHOTWINS_CONFIG);
