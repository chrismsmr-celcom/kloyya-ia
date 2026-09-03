/**
 * Kloyya Wire — Connecte le prototype au backend
 * Ce fichier remplace les actions simulées par de vrais appels API
 */

(function() {
  'use strict';

  // Attendre que le DOM soit chargé
  document.addEventListener('DOMContentLoaded', function() {
    console.log('[Kloyya] Initializing wire...');

    // --- AUTH ---
    wireAuth();
    
    // --- ONBOARDING ---
    wireOnboarding();
    
    // --- COMPOSER ---
    wireComposer();
    
    // --- PLAN REVIEW ---
    wirePlanReview();
    
    // --- LIVE RUN ---
    wireLiveRun();
    
    // --- CONNECTIONS ---
    wireConnections();
    
    // --- DASHBOARD ---
    wireDashboard();
  });

  // ============================================
  // 1. AUTH (Signup / Login)
  // ============================================
  function wireAuth() {
    // Bouton "Create workspace" sur Signup
    const signupBtn = document.querySelector('[sc-camel-on-click="goOnboarding"]');
    if (signupBtn) {
      signupBtn.addEventListener('click', async function(e) {
        e.preventDefault();
        
        // Récupérer l'email et le password du formulaire
        const email = document.querySelector('div:contains("Work email") + div')?.textContent?.trim() || 'demo@kloyya.com';
        const password = 'password123'; // À remplacer par un vrai champ
        
        try {
          // 1. Signup avec Supabase
          const { data, error } = await window.supabase.auth.signUp({
            email: email,
            password: password,
          });
          
          if (error) throw error;
          
          // 2. Provisionner le workspace
          const result = await window.KloyyaAPI.provisionWorkspace();
          console.log('[Kloyya] Workspace created:', result);
          
          // 3. Rediriger vers onboarding
          window.location.hash = '#onboarding';
          
        } catch (err) {
          console.error('[Kloyya] Signup error:', err);
          alert('Erreur lors de la création du compte: ' + err.message);
        }
      });
    }

    // Bouton "Log in" sur Login
    const loginBtn = document.querySelector('[sc-camel-on-click="goDash"]');
    if (loginBtn) {
      loginBtn.addEventListener('click', async function(e) {
        e.preventDefault();
        
        const email = document.querySelector('div:contains("Work email") + div')?.textContent?.trim() || 'demo@kloyya.com';
        const password = 'password123';
        
        try {
          const { data, error } = await window.supabase.auth.signInWithPassword({
            email: email,
            password: password,
          });
          
          if (error) throw error;
          
          // Rediriger vers le dashboard
          window.location.hash = '#dashboard';
          
        } catch (err) {
          console.error('[Kloyya] Login error:', err);
          alert('Erreur de connexion: ' + err.message);
        }
      });
    }
  }

  // ============================================
  // 2. ONBOARDING
  // ============================================
  function wireOnboarding() {
    // Bouton "Continue" sur la première page
    const continueBtn = document.querySelector('[sc-camel-on-click="toStep1"]');
    if (continueBtn) {
      continueBtn.addEventListener('click', function(e) {
        // Récupérer la persona sélectionnée
        const selected = document.querySelector('[style*="border-color: #2159C5"]');
        if (selected) {
          const persona = selected.getAttribute('data-persona') || 'work';
          window._kloyya_onboarding = window._kloyya_onboarding || {};
          window._kloyya_onboarding.persona = persona;
        }
      });
    }

    // Bouton "Continue" sur la page des rôles
    const roleContinueBtn = document.querySelector('[sc-camel-on-click="toStep2"]');
    if (roleContinueBtn) {
      roleContinueBtn.addEventListener('click', function(e) {
        const selected = document.querySelector('[style*="font-weight: 550"]');
        if (selected) {
          window._kloyya_onboarding = window._kloyya_onboarding || {};
          window._kloyya_onboarding.role = selected.textContent.trim();
        }
      });
    }

    // Bouton "Continue" sur la page des goals
    const goalContinueBtn = document.querySelector('[sc-camel-on-click="toStep3"]');
    if (goalContinueBtn) {
      goalContinueBtn.addEventListener('click', function(e) {
        const selected = document.querySelector('[style*="border-color: #2159C5"]');
        if (selected) {
          window._kloyya_onboarding = window._kloyya_onboarding || {};
          window._kloyya_onboarding.goal = selected.textContent.trim();
        }
      });
    }

    // Bouton "Continue" sur la page des outils
    const toolsContinueBtn = document.querySelector('[sc-camel-on-click="toStep4"]');
    if (toolsContinueBtn) {
      toolsContinueBtn.addEventListener('click', function(e) {
        const selected = document.querySelectorAll('[style*="border-color: #2159C5"]');
        const tools = [];
        selected.forEach(el => {
          const name = el.querySelector('span:last-child')?.textContent?.trim();
          if (name) tools.push(name.toLowerCase());
        });
        window._kloyya_onboarding = window._kloyya_onboarding || {};
        window._kloyya_onboarding.tools = tools;
      });
    }

    // Bouton "That's right — pick a plan"
    const confirmBtn = document.querySelector('[sc-camel-on-click="goPricing"]');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', async function(e) {
        e.preventDefault();
        
        const data = window._kloyya_onboarding || {};
        
        try {
          const result = await window.KloyyaAPI.completeOnboarding({
            persona: data.persona || 'work',
            role: data.role || 'Manager',
            firstOutcome: data.goal || 'Tell me which customers are about to churn and why',
            requestedTools: data.tools || ['slack', 'gmail']
          });
          
          console.log('[Kloyya] Onboarding completed:', result);
          
          // Rediriger vers la page des plans
          window.location.hash = '#pricing';
          
        } catch (err) {
          console.error('[Kloyya] Onboarding error:', err);
          alert('Erreur lors de l\'enregistrement: ' + err.message);
        }
      });
    }
  }

  // ============================================
  // 3. COMPOSER (New Outcome)
  // ============================================
  function wireComposer() {
    // Bouton "Draft a plan"
    const draftBtn = document.querySelector('[sc-camel-on-click="submit"]');
    if (draftBtn) {
      draftBtn.addEventListener('click', async function(e) {
        e.preventDefault();
        
        const textarea = document.querySelector('textarea');
        const title = textarea?.value?.trim() || 'Find at-risk accounts';
        
        try {
          // 1. Créer l'outcome
          const outcome = await window.KloyyaAPI.createOutcome(title, {});
          console.log('[Kloyya] Outcome created:', outcome);
          
          // 2. Clarifier (si nécessaire)
          // Le backend va générer une question si besoin
          
          // 3. Récupérer le plan
          const plan = await window.KloyyaAPI.getPlan(outcome.id);
          console.log('[Kloyya] Plan:', plan);
          
          // Stocker l'outcome ID pour la suite
          window._kloyya_current_outcome = outcome.id;
          
          // Rediriger vers la page du plan
          window.location.hash = '#plan';
          
        } catch (err) {
          console.error('[Kloyya] Create outcome error:', err);
          alert('Erreur: ' + err.message);
        }
      });
    }

    // Suggestions (chips)
    const suggestions = document.querySelectorAll('[sc-camel-on-click^="fill"]');
    suggestions.forEach((chip, index) => {
      chip.addEventListener('click', function(e) {
        // Le texte est déjà dans l'attribut `sc-camel-on-click`
        // On laisse le prototype gérer l'affichage
        console.log('[Kloyya] Suggestion selected:', this.textContent.trim());
      });
    });
  }

  // ============================================
  // 4. PLAN REVIEW
  // ============================================
  function wirePlanReview() {
    // Bouton "Run"
    const runBtn = document.querySelector('[sc-camel-on-click="goRun"]');
    if (runBtn) {
      runBtn.addEventListener('click', async function(e) {
        e.preventDefault();
        
        const outcomeId = window._kloyya_current_outcome;
        if (!outcomeId) {
          alert('Aucun outcome en cours. Créez-en un d\'abord.');
          return;
        }
        
        try {
          // Démarrer le run
          const run = await window.KloyyaAPI.runOutcome(outcomeId);
          console.log('[Kloyya] Run started:', run);
          
          // Rediriger vers le live run
          window.location.hash = '#run';
          
        } catch (err) {
          console.error('[Kloyya] Run error:', err);
          alert('Erreur: ' + err.message);
        }
      });
    }

    // "Save as template" (juste log pour l'instant)
    const saveBtn = document.querySelector('button:contains("Save as template")');
    if (saveBtn) {
      saveBtn.addEventListener('click', function(e) {
        console.log('[Kloyya] Save as template (not implemented yet)');
      });
    }
  }

  // ============================================
  // 5. LIVE RUN
  // ============================================
  function wireLiveRun() {
    // Quand la page s'affiche, on connecte le SSE
    const runObserver = new MutationObserver(function() {
      if (window.location.hash === '#run') {
        connectSSE();
        runObserver.disconnect();
      }
    });
    
    runObserver.observe(document.body, {
      childList: true,
      subtree: true
    });
    
    async function connectSSE() {
      const outcomeId = window._kloyya_current_outcome;
      if (!outcomeId) return;
      
      try {
        const eventSource = await window.KloyyaAPI.streamOutcome(outcomeId, {
          onStep: function(data) {
            console.log('[SSE] Step:', data);
            updateStepUI(data);
          },
          onLog: function(data) {
            console.log('[SSE] Log:', data);
            addLogLine(data);
          },
          onProgress: function(data) {
            console.log('[SSE] Progress:', data);
            updateProgressBar(data);
          },
          onFinding: function(data) {
            console.log('[SSE] Finding:', data);
            showFinding(data);
          },
          onState: function(data) {
            console.log('[SSE] State:', data);
            updateState(data);
          },
          onDone: function(data) {
            console.log('[SSE] Done:', data);
            window.location.hash = '#detail';
          }
        });
        
        window._kloyya_sse = eventSource;
        
      } catch (err) {
        console.error('[Kloyya] SSE error:', err);
      }
    }
  }

  // ============================================
  // 6. CONNECTIONS
  // ============================================
  function wireConnections() {
    // Charger les connexions quand la page s'affiche
    const connObserver = new MutationObserver(async function() {
      if (window.location.hash === '#integrations') {
        await loadConnections();
        connObserver.disconnect();
      }
    });
    
    connObserver.observe(document.body, {
      childList: true,
      subtree: true
    });
    
    async function loadConnections() {
      try {
        const connections = await window.KloyyaAPI.listConnections();
        console.log('[Kloyya] Connections:', connections);
        
        // Mettre à jour l'UI avec les vraies données
        updateConnectionsUI(connections);
        
      } catch (err) {
        console.error('[Kloyya] Load connections error:', err);
      }
    }

    // Boutons "Connect" sur chaque outil
    document.addEventListener('click', function(e) {
      const btn = e.target.closest('button:contains("Connect")');
      if (btn) {
        const toolName = btn.closest('[style*="border"]')?.querySelector('span:first-child')?.textContent?.toLowerCase();
        if (toolName) {
          window.KloyyaAPI.authorizeConnection(toolName);
        }
      }
    });
  }

  // ============================================
  // 7. DASHBOARD
  // ============================================
  function wireDashboard() {
    // Charger les données quand la page s'affiche
    const dashObserver = new MutationObserver(async function() {
      if (window.location.hash === '#dashboard' || window.location.hash === '') {
        await loadDashboard();
        dashObserver.disconnect();
      }
    });
    
    dashObserver.observe(document.body, {
      childList: true,
      subtree: true
    });
    
    async function loadDashboard() {
      try {
        // 1. Charger les outcomes
        const outcomes = await window.KloyyaAPI.listOutcomes();
        console.log('[Kloyya] Outcomes:', outcomes);
        
        // 2. Charger l'impact
        const impact = await window.KloyyaAPI.getImpact();
        console.log('[Kloyya] Impact:', impact);
        
        // Mettre à jour l'UI
        updateDashboardUI(outcomes, impact);
        
      } catch (err) {
        console.error('[Kloyya] Load dashboard error:', err);
      }
    }
  }

  // ============================================
  // HELPERS UI - Mise à jour du DOM
  // ============================================

  function updateStepUI(data) {
    // Mettre à jour le step en cours dans le live run
    const steps = document.querySelectorAll('[data-step]');
    steps.forEach(el => {
      const stepId = el.getAttribute('data-step');
      if (stepId === data.stepId) {
        el.style.borderColor = '#2159C5';
        el.style.background = '#FAFCFF';
        el.querySelector('[data-status]').textContent = data.state;
      }
    });
  }

  function addLogLine(data) {
    // Ajouter une ligne dans le log
    const logContainer = document.querySelector('[data-log]');
    if (!logContainer) return;
    
    const colors = {
      auth: '#6B7079',
      read: '#4C8B6B',
      filter: '#6B7079',
      rule: '#B08A4C',
      signal: '#7C93C9',
      gap: '#C08A4C',
      insight: '#7C93C9',
      notify: '#B08A4C',
      reason: '#7C93C9'
    };
    
    const line = document.createElement('div');
    line.style.cssText = 'display:flex;gap:10px;padding:4px 0;font-family:monospace;font-size:11px;';
    line.innerHTML = `
      <span style="color:#4E535B;flex-shrink:0">${data.ts || 'now'}</span>
      <span style="color:${colors[data.tag] || '#A7ACB4'};flex-shrink:0;width:52px">${data.tag}</span>
      <span style="color:#A7ACB4;min-width:0">${data.message}</span>
    `;
    logContainer.appendChild(line);
  }

  function updateProgressBar(data) {
    // Mettre à jour la barre de progression
    const bar = document.querySelector('[data-progress]');
    if (bar) {
      bar.style.width = data.pct + '%';
    }
  }

  function showFinding(data) {
    // Afficher une finding
    const container = document.querySelector('[data-findings]');
    if (!container) return;
    
    const finding = document.createElement('div');
    finding.style.cssText = 'border:1px solid #F0DEBF;background:#FFFBF4;border-radius:11px;padding:18px 20px;margin-top:16px;';
    finding.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-family:monospace;font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:#8C5A13">Found something · mid-run</span>
        <span style="margin-left:auto;font-family:monospace;font-size:10.5px;color:#B79A6A">now</span>
      </div>
      <div style="font-style:italic;font-size:18px;line-height:1.5;color:#1D2026;margin-top:11px">${data.body}</div>
    `;
    container.appendChild(finding);
  }

  function updateState(data) {
    // Mettre à jour l'état de l'outcome
    const stateBadge = document.querySelector('[data-state]');
    if (stateBadge) {
      stateBadge.textContent = data.state.toUpperCase();
      stateBadge.style.background = data.state === 'delivered' ? '#EDF6F1' : '#EDF2FD';
      stateBadge.style.color = data.state === 'delivered' ? '#2C7A55' : '#2159C5';
    }
  }

  function updateConnectionsUI(connections) {
    // Mettre à jour les connexions dans l'UI
    const containers = document.querySelectorAll('[data-connection]');
    containers.forEach(el => {
      const toolId = el.getAttribute('data-connection');
      const conn = connections.find(c => c.tool_id === toolId);
      if (conn) {
        const dot = el.querySelector('[data-dot]');
        if (dot) {
          dot.style.background = conn.state === 'connected' ? '#2C7A55' : '#DDD8CE';
        }
        const status = el.querySelector('[data-status]');
        if (status) {
          status.textContent = conn.state === 'connected' ? 'CONNECTED' : 'NOT CONNECTED';
          status.style.color = conn.state === 'connected' ? '#2C7A55' : '#A8A296';
        }
      }
    });
  }

  function updateDashboardUI(outcomes, impact) {
    // Mettre à jour le dashboard
    const impactEls = document.querySelectorAll('[data-impact]');
    if (impactEls.length > 0 && impact) {
      const keys = ['totalDelivered', 'avgDurationMs', 'activeConnections', 'writesExecuted'];
      impactEls.forEach((el, i) => {
        const key = keys[i];
        if (key && impact[key] !== undefined) {
          const valEl = el.querySelector('[data-value]');
          if (valEl) {
            valEl.textContent = key === 'avgDurationMs' ? Math.round(impact[key] / 1000) + 's' : impact[key];
          }
        }
      });
    }

    // Mettre à jour la liste des outcomes
    const list = document.querySelector('[data-outcomes-list]');
    if (list && outcomes) {
      list.innerHTML = '';
      outcomes.forEach(o => {
        const row = document.createElement('div');
        row.style.cssText = 'display:grid;grid-template-columns:2.4fr .9fr 1fr 1.1fr .8fr;gap:16px;padding:15px 14px;align-items:center;border-top:1px solid #EFEBE3;cursor:pointer';
        row.innerHTML = `
          <div>
            <div style="font-size:13.5px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${o.title}</div>
          </div>
          <div>
            <span style="display:inline-flex;align-items:center;gap:6px;font-family:monospace;font-size:10px;padding:3px 8px;border-radius:5px;background:${o.state === 'delivered' ? '#EDF6F1' : '#EDF2FD'};color:${o.state === 'delivered' ? '#2C7A55' : '#2159C5'}">
              <span style="width:5px;height:5px;border-radius:50%;background:${o.state === 'delivered' ? '#2C7A55' : '#2159C5'}"></span>
              ${o.state.toUpperCase()}
            </span>
          </div>
          <div style="font-size:12.5px;color:#7D786F">${o.duration_ms ? Math.round(o.duration_ms / 1000) + 's' : '—'}</div>
          <div style="font-size:11px;font-family:monospace;color:#9A948A">${new Date(o.created_at).toLocaleDateString()}</div>
        `;
        row.addEventListener('click', () => {
          window.location.hash = '#detail';
        });
        list.appendChild(row);
      });
    }
  }

  // ============================================
  // UTILS
  // ============================================
  
  // Helper: sélecteur ":contains"
  CSS.escape = CSS.escape || function(value) {
    return String(value).replace(/([!"#$%&'()*+,./:;<=>?@[\\\]^`{|}~])/g, '\\$1');
  };

  document.querySelectorAll('*').forEach(el => {
    const onclick = el.getAttribute('sc-camel-on-click');
    if (onclick && onclick.startsWith('go') && !el._wired) {
      el._wired = true;
      // On laisse le prototype gérer le routing
    }
  });

  console.log('[Kloyya] Wire initialized successfully.');
})();
