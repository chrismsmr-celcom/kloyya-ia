/**
 * Kloyya API client — fichier autonome, à ajouter en <script> dans
 * index.html / Kloyya-prototype.html SANS modifier ces fichiers.
 * Il expose `window.KloyyaAPI`; le prototype reste inchangé, c'est lui
 * qui viendra appeler ces fonctions depuis ses propres gestionnaires
 * d'événements (ou via de petits scripts additionnels que vous ajoutez
 * à côté, cf. INTEGRATION.md).
 *
 * Auth : on suppose que le client Supabase JS (@supabase/supabase-js)
 * est déjà chargé sur la page et gère signup/login/session. Ce fichier
 * lit juste le token de session courant pour l'attacher aux requêtes.
 */
(function () {
  const API_BASE = window.KLOYYA_API_BASE || "http://localhost:8000";

  async function getAccessToken() {
    if (!window.supabase) {
      throw new Error("Supabase JS client not found on window.supabase — load it before api-client.js");
    }
    const { data } = await window.supabase.auth.getSession();
    return data.session ? data.session.access_token : null;
  }

  async function request(path, options = {}) {
    const token = await getAccessToken();
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      options.headers || {},
      token ? { Authorization: `Bearer ${token}` } : {}
    );
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`Kloyya API ${res.status}: ${body}`);
    }
    const contentType = res.headers.get("content-type") || "";
    return contentType.includes("application/json") ? res.json() : res.text();
  }

  const KloyyaAPI = {
    // ---- Outcomes (spec webapp §3) ----
    createOutcome: (title, scope) =>
      request("/api/outcomes", { method: "POST", body: JSON.stringify({ title, scope }) }),

    clarifyOutcome: (outcomeId, answer) =>
      request(`/api/outcomes/${outcomeId}/clarify`, { method: "POST", body: JSON.stringify({ answer }) }),

    getPlan: (outcomeId) => request(`/api/outcomes/${outcomeId}/plan`),

    updatePlan: (outcomeId, steps) =>
      request(`/api/outcomes/${outcomeId}/plan`, { method: "PATCH", body: JSON.stringify({ steps }) }),

    runOutcome: (outcomeId, idempotencyKey) =>
      request(`/api/outcomes/${outcomeId}/run`, {
        method: "POST",
        headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
      }),

    /** Ouvre le flux SSE du Live run. Retourne l'EventSource — appelant gère .close(). */
    streamOutcome: async (outcomeId, handlers) => {
      const token = await getAccessToken();
      // EventSource natif ne supporte pas les headers custom -> on passe le
      // token en query param côté serveur si besoin, ou on utilise fetch-event-source.
      // Ici : approche simple avec un endpoint qui accepte ?access_token=.
      const es = new EventSource(`${API_BASE}/api/outcomes/${outcomeId}/stream?access_token=${token}`);
      if (handlers.onStep) es.addEventListener("step", (e) => handlers.onStep(JSON.parse(e.data)));
      if (handlers.onLog) es.addEventListener("log", (e) => handlers.onLog(JSON.parse(e.data)));
      if (handlers.onProgress) es.addEventListener("progress", (e) => handlers.onProgress(JSON.parse(e.data)));
      if (handlers.onFinding) es.addEventListener("finding", (e) => handlers.onFinding(JSON.parse(e.data)));
      if (handlers.onState) es.addEventListener("state", (e) => handlers.onState(JSON.parse(e.data)));
      if (handlers.onDone) es.addEventListener("done", (e) => { handlers.onDone(JSON.parse(e.data)); es.close(); });
      return es;
    },

    pauseOutcome: (outcomeId) => request(`/api/outcomes/${outcomeId}/pause`, { method: "POST" }),
    cancelOutcome: (outcomeId) => request(`/api/outcomes/${outcomeId}/cancel`, { method: "POST" }),
    respondToFinding: (outcomeId, findingId, response) =>
      request(`/api/outcomes/${outcomeId}/findings/${findingId}`, { method: "POST", body: JSON.stringify({ response }) }),
    getOutcomeDetail: (outcomeId) => request(`/api/outcomes/${outcomeId}`),
    approveArtifacts: (outcomeId, artifactIds) =>
      request(`/api/outcomes/${outcomeId}/approve`, { method: "POST", body: JSON.stringify({ artifactIds }) }),
    listOutcomes: (state) => request(`/api/outcomes${state ? `?state=${state}` : ""}`),
    transcribe: (outcomeId, audioBlob) => {
      const form = new FormData();
      form.append("audio", audioBlob, "recording.webm");
      return request(`/api/outcomes/${outcomeId}/transcribe`, { method: "POST", body: form, headers: {} });
    },

    // ---- Connections (spec webapp §5) ----
    listConnections: () => request("/api/connections"),
    authorizeConnection: (toolId) => { window.location.href = `${API_BASE}/api/connections/${toolId}/authorize`; },
    updateConnectionScopes: (toolId, resources) =>
      request(`/api/connections/${toolId}/scopes`, { method: "PATCH", body: JSON.stringify({ resources }) }),
    revokeConnection: (toolId) => request(`/api/connections/${toolId}`, { method: "DELETE" }),

    // ---- Memory ----
    listMemory: () => request("/api/memory"),
    retractMemory: (factId) => request(`/api/memory/${factId}`, { method: "DELETE" }),

    // ---- Impact dashboard ----
    getImpact: () => request("/api/impact"),

    // ---- Documents (RAG) ----
    uploadDocument: (file) => {
      const form = new FormData();
      form.append("file", file);
      return request("/api/documents", { method: "POST", body: form, headers: {} });
    },
    listDocuments: () => request("/api/documents"),
    deleteDocument: (documentId) => request(`/api/documents/${documentId}`, { method: "DELETE" }),

    // ---- Onboarding / billing (spec landing) ----
    provisionWorkspace: () => request("/api/onboarding/provision-workspace", { method: "POST" }),
    getPersonaConfig: (persona) => request(`/api/onboarding/persona-config/${persona}`),
    completeOnboarding: (payload) => request("/api/onboarding", { method: "POST", body: JSON.stringify(payload) }),
    getSubscription: () => request("/api/billing/subscription"),
    subscribe: (tierId, cadence, paymentMethodId) =>
      request("/api/billing/subscribe", { method: "POST", body: JSON.stringify({ tierId, cadence, paymentMethodId }) }),
  };

  window.KloyyaAPI = KloyyaAPI;
})();