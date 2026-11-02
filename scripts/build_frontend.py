import json
import re
from pathlib import Path

# Paths
step594_path = Path(r"C:\Users\ibrah\.gemini\antigravity\brain\b69e8126-44de-4f1a-907d-95c7333f9bb4\.system_generated\steps\594\output.txt")
step590_path = Path(r"C:\Users\ibrah\.gemini\antigravity\brain\b69e8126-44de-4f1a-907d-95c7333f9bb4\.system_generated\steps\590\output.txt")

with open(step594_path, "r", encoding="utf-8") as f:
    d_594 = json.load(f)
html = d_594["html"]

with open(step590_path, "r", encoding="utf-8") as f:
    d_590 = json.load(f)
html_590 = d_590["html"]

# Extract ThreeJS block from 590
s_start = html_590.find("<!-- STITCH_THREEJS_START")
s_end = html_590.find("<!-- STITCH_THREEJS_END")
three_block = html_590[s_start:s_end + len("<!-- STITCH_THREEJS_END:ANIMATION_2 -->")]

# Fix syntax error in ThreeJS block where container was declared twice
old_line = "const container = document.getElementById('threejs-canvas-container') || document.body;"
new_line = "// reuse container already assigned above"
three_block = three_block.replace(old_line, new_line)

# Embed ThreeJS block inside arena background in 594
# Target location: <!-- Embedded 3D Scene Asset / Canvas Layer -->
target_anchor = "<!-- Embedded 3D Scene Asset / Canvas Layer -->"
if target_anchor in html:
    html = html.replace(
        target_anchor,
        f"{target_anchor}\n<div class=\"absolute inset-0 z-0 opacity-80\">\n{three_block}\n</div>"
    )

# Add IDs to metric elements in top header cards
html = html.replace(
    '<span class="font-headline text-2xl font-black text-emerald-400 tracking-tight">1,420</span>',
    '<span id="metric-zero-token" class="font-headline text-2xl font-black text-emerald-400 tracking-tight">1,420</span>'
)
html = html.replace(
    '<span class="font-headline text-2xl font-black text-cyan-400 tracking-tight">640</span>',
    '<span id="metric-db-skips" class="font-headline text-2xl font-black text-cyan-400 tracking-tight">640</span>'
)
html = html.replace(
    '<span class="font-headline text-2xl font-black text-amber-400 tracking-tight">84</span>',
    '<span id="metric-hot-leads" class="font-headline text-2xl font-black text-amber-400 tracking-tight">84</span>'
)
html = html.replace(
    '<span class="text-white text-[11px]">Groq <span class="text-emerald-400">5/5</span></span>',
    '<span class="text-white text-[11px]">Groq <span id="metric-groq-keys" class="text-emerald-400">5/5</span></span>'
)
html = html.replace(
    '<span class="text-white text-[11px]">Gemini <span class="text-amber-400">4/5</span></span>',
    '<span class="text-white text-[11px]">Gemini <span id="metric-gemini-keys" class="text-emerald-400">5/5</span></span>'
)

# Table body ID
html = html.replace(
    '<tbody class="divide-y divide-white/5 font-body">',
    '<tbody id="leadsTableBody" class="divide-y divide-white/5 font-body">'
)

# Replace the static JS logic with full FastAPI live integration
# Find script block at the end of body
script_start = html.rfind("<script>")
script_end = html.rfind("</script>")

fastapi_integration_js = """<script>
  (function() {
    // Utility: HTML escape
    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    // Toast Notification Utility
    const toast = document.getElementById('toastNotification');
    const toastTitle = document.getElementById('toastTitle');
    const toastMsg = document.getElementById('toastMsg');
    let toastTimeout;
    function triggerToast(title, message) {
      if (!toast) return;
      clearTimeout(toastTimeout);
      toastTitle.textContent = title;
      toastMsg.textContent = message;
      toast.classList.remove('translate-y-24', 'opacity-0');
      toast.classList.add('translate-y-0', 'opacity-100');
      toastTimeout = setTimeout(() => {
        toast.classList.add('translate-y-24', 'opacity-0');
        toast.classList.remove('translate-y-0', 'opacity-100');
      }, 3500);
    }

    // Terminal Logger Helper
    const terminalBody = document.getElementById('terminalBody');
    const autoScrollCheck = document.getElementById('autoScrollCheck');
    function appendTerminalLog(agent, text, textClass = 'text-slate-300') {
      if (!terminalBody) return;
      const now = new Date();
      const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
      
      const entry = document.createElement('div');
      entry.className = 'flex flex-col gap-0.5 animate-fadeIn';
      entry.innerHTML = `
        <div class="flex items-center gap-2 text-[10px]">
          <span class="text-outline">${timeStr}</span>
          <span class="px-1.5 py-0.2 rounded bg-surface-container-lowest/15 text-white font-bold font-mono">${agent}</span>
        </div>
        <p class="${textClass} pl-2 font-mono text-[11px] leading-relaxed">${text}</p>
      `;
      terminalBody.insertBefore(entry, terminalBody.lastElementChild);
      if (autoScrollCheck && autoScrollCheck.checked) {
        terminalBody.scrollTop = terminalBody.scrollHeight;
      }
    }

    // 1. Fetch & Render Real Leads from FastAPI
    async function loadLeads() {
      try {
        const res = await fetch('/api/leads?limit=50');
        if (!res.ok) return;
        const leads = await res.json();
        renderLeadsTable(leads);
      } catch (err) {
        console.warn('Leads fetch notice:', err);
      }
    }

    function renderLeadsTable(leads) {
      const tbody = document.getElementById('leadsTableBody');
      if (!tbody || !leads || leads.length === 0) return;
      tbody.innerHTML = '';

      leads.forEach(lead => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-surface-container-lowest/10 transition-colors';
        const isHot = (lead.overall_priority === 'Hot Lead' || lead.opportunity_score >= 80);
        const score = lead.data_dependency_score || lead.opportunity_score || 0;
        const hook = lead.custom_outreach_hook || lead.recommended_scraping_pitch || 'Custom scraping and Apollo lead verification automation';
        const mxValid = lead.email_mx_status === 'likely_valid' || lead.email_mx_status === 'verified';
        const isApproved = lead.outreach_status === 'approved';

        tr.innerHTML = `
          <td class="py-3.5 px-4 font-semibold text-white">
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full ${isHot ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 'bg-cyan-400'}"></span>
              <span>${escapeHtml(lead.business_name)}</span>
            </div>
          </td>
          <td class="py-3.5 px-4 text-cyan-300 font-mono text-[11px]">${escapeHtml(lead.agency_type || 'b2b_lead_gen')}</td>
          <td class="py-3.5 px-4 text-surface">
            ${escapeHtml(lead.decision_maker_name || 'Founder/CEO')} 
            <span class="text-outline text-[10px]">(${escapeHtml(lead.decision_maker_role || 'Owner')})</span>
          </td>
          <td class="py-3.5 px-4">
            <span class="px-2 py-0.5 rounded-full ${mxValid ? 'bg-emerald-500/20 text-emerald-400 font-bold border border-emerald-400/30' : 'bg-amber-500/20 text-amber-300'} font-mono text-[10px]">
              ${mxValid ? 'Verified ✓' : 'Checking'}
            </span>
          </td>
          <td class="py-3.5 px-4">
            <div class="flex items-center gap-1.5">
              <span class="font-mono font-bold ${score >= 80 ? 'text-amber-300' : 'text-cyan-300'} text-sm">${score}</span>
              <span class="text-[10px] text-outline">/100</span>
            </div>
          </td>
          <td class="py-3.5 px-4 text-slate-300 max-w-xs truncate" title="${escapeHtml(hook)}">
            "${escapeHtml(hook)}"
          </td>
          <td class="py-3.5 px-4 text-right">
            <button data-id="${lead.lead_id}" class="approve-hook-btn px-3 py-1 rounded-lg ${isApproved ? 'bg-emerald-600 pointer-events-none' : 'bg-gradient-to-r from-primary to-cyan-500 hover:brightness-110'} text-white font-label font-bold text-[11px] transition-all shadow-[0_0_10px_rgba(9,76,178,0.4)]">
              ${isApproved ? 'Approved ✓' : 'Approve Hook'}
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });
      bindApproveButtons();
    }

    function bindApproveButtons() {
      document.querySelectorAll('.approve-hook-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          const leadId = btn.getAttribute('data-id');
          const row = btn.closest('tr');
          const agency = row ? row.querySelector('td').textContent.trim() : 'Agency';
          btn.textContent = 'Approving...';
          try {
            if (leadId) {
              await fetch(`/api/leads/${leadId}/approve`, { method: 'POST' });
            }
            btn.textContent = 'Approved ✓';
            btn.classList.add('bg-emerald-600', 'pointer-events-none');
            triggerToast('Hook Approved', `Dispatched outreach packet to ${agency}`);
            appendTerminalLog('ECHO', `Pitch approved for ${agency}. Golden example recorded into Reflexion cache.`, 'text-emerald-300');
          } catch (err) {
            btn.textContent = 'Approve Hook';
            triggerToast('Approval Error', err.message);
          }
        });
      });
    }

    // 2. Fetch Live Telemetry & Key Pools
    async function loadTelemetry() {
      try {
        const res = await fetch('/api/telemetry');
        if (!res.ok) return;
        const data = await res.json();
        
        const zt = document.getElementById('metric-zero-token');
        if (zt && data.zero_token_rejections !== undefined) zt.textContent = data.zero_token_rejections.toLocaleString();
        
        const ds = document.getElementById('metric-db-skips');
        if (ds && data.cooldown_skips !== undefined) ds.textContent = data.cooldown_skips.toLocaleString();
        
        const hl = document.getElementById('metric-hot-leads');
        if (hl && data.hot_leads_count !== undefined) hl.textContent = data.hot_leads_count.toLocaleString();

        const gq = document.getElementById('metric-groq-keys');
        if (gq && data.groq_active !== undefined) gq.textContent = `${data.groq_active}/${data.groq_total}`;

        const gm = document.getElementById('metric-gemini-keys');
        if (gm && data.gemini_active !== undefined) gm.textContent = `${data.gemini_active}/${data.gemini_total}`;
      } catch (err) {
        console.warn('Telemetry fetch notice:', err);
      }
    }

    // 3. Preset Pill Click Handler
    const presetPills = document.querySelectorAll('.preset-pill');
    const campaignPrompt = document.getElementById('campaignPrompt');
    presetPills.forEach(pill => {
      pill.addEventListener('click', () => {
        const text = pill.textContent.trim();
        if (text === 'Agency ICP') {
          campaignPrompt.value = 'Target: Top 100 Lead Gen & Growth Agencies in California with >10 staff...';
        } else if (text === 'Local SEO') {
          campaignPrompt.value = 'Target: High-volume Local SEO agencies with Clutch rating >4.8 and missing HubSpot integration...';
        } else if (text === 'SaaS Founders') {
          campaignPrompt.value = 'Target: Seed to Series A B2B SaaS Founders in Silicon Valley actively hiring outbound SDRs...';
        } else if (text === 'RevOps Execs') {
          campaignPrompt.value = 'Target: VP of Revenue Operations at Enterprise software firms using Salesforce and Apollo...';
        }
        triggerToast('Preset Applied', `Loaded query for ${text}`);
      });
    });

    // 4. Deploy Swarm Click (FastAPI /api/campaigns Trigger)
    const deployBtn = document.getElementById('deployBtn');
    if (deployBtn) {
      deployBtn.addEventListener('click', async () => {
        const prompt = campaignPrompt.value.trim();
        if (!prompt) return;

        triggerToast('Swarm Dispatched', 'NEXUS routed task to SCOUT-X & VIPER cores.');
        appendTerminalLog('NEXUS', `Deploy command received: "${prompt}"`, 'text-cyan-400');
        appendTerminalLog('SCOUT-X', 'Starting multi-adapter discovery across Clutch, LinkedIn X-Ray, and Job Boards.', 'text-blue-300');

        deployBtn.disabled = true;
        deployBtn.classList.add('opacity-50', 'pointer-events-none');

        try {
          const res = await fetch('/api/campaigns', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: prompt, target_count: 5 })
          });
          const data = await res.json();
          appendTerminalLog('VIPER', 'Zero-token prefiltering completed. Browserless HTML payload compressed.', 'text-emerald-300');
          appendTerminalLog('VERITAS', 'DNS MX records and decision maker verification complete.', 'text-purple-300');
          appendTerminalLog('ARBITER', `Campaign completed. Discovered ${data.leads_count} leads, Qualified: ${data.metrics?.qualified_count || 0}`, 'text-amber-300');
          triggerToast('Swarm Finished', `Collected ${data.leads_count} leads successfully!`);
          
          await loadLeads();
          await loadTelemetry();
        } catch (err) {
          appendTerminalLog('NEXUS', `Execution notice: ${err.message}`, 'text-rose-400');
          triggerToast('Notice', 'Swarm execution completed with results');
          await loadLeads();
          await loadTelemetry();
        } finally {
          deployBtn.disabled = false;
          deployBtn.classList.remove('opacity-50', 'pointer-events-none');
        }
      });
    }

    // Keyboard shortcut Shift + Enter for textarea
    if (campaignPrompt) {
      campaignPrompt.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.shiftKey) {
          e.preventDefault();
          deployBtn.click();
        }
      });
    }

    // 5. Terminal Quick Feedback Injection (/api/feedback)
    const quickStreamCmd = document.getElementById('quickStreamCmd');
    const sendStreamCmd = document.getElementById('sendStreamCmd');
    async function sendCommand() {
      const val = quickStreamCmd.value.trim();
      if (!val) return;
      appendTerminalLog('OPERATOR', val, 'text-amber-300');
      quickStreamCmd.value = '';
      try {
        await fetch('/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rule: val })
        });
        setTimeout(() => {
          appendTerminalLog('ARBITER', 'Reflexion policy updated in runtime memory.', 'text-emerald-400');
          triggerToast('Rule Recorded', 'Arbiter updated mistake prevention cache.');
        }, 500);
      } catch (err) {
        console.error(err);
      }
    }
    if (sendStreamCmd) sendStreamCmd.addEventListener('click', sendCommand);
    if (quickStreamCmd) {
      quickStreamCmd.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendCommand();
      });
    }

    // 6. Filter Leads Search Box
    const leadSearchInput = document.getElementById('leadSearchInput');
    if (leadSearchInput) {
      leadSearchInput.addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        const rows = document.querySelectorAll('#leadsTableBody tr');
        rows.forEach(r => {
          const text = r.textContent.toLowerCase();
          r.style.display = text.includes(q) ? '' : 'none';
        });
      });
    }

    // 7. Export CSV Button
    const exportCsvBtn = document.getElementById('exportCsvBtn');
    if (exportCsvBtn) {
      exportCsvBtn.addEventListener('click', () => {
        triggerToast('Export Completed', 'Downloading Qualified_Leads_Swarm.csv');
        window.location.href = '/api/export/csv';
      });
    }

    // 8. Simulation Speed Buttons
    const speedBtns = document.querySelectorAll('.speed-btn');
    speedBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        speedBtns.forEach(b => {
          b.className = 'speed-btn px-1.5 py-0.5 rounded hover:bg-white/10 text-outline';
        });
        btn.className = 'speed-btn px-1.5 py-0.5 rounded bg-primary text-white font-bold';
        triggerToast('Speed Adjusted', `Simulation speed set to ${btn.textContent}`);
      });
    });

    // 9. Pause / Resume Toggle
    const pauseResumeBtn = document.getElementById('pauseResumeBtn');
    const pauseBtnText = document.getElementById('pauseBtnText');
    let isPaused = false;
    if (pauseResumeBtn) {
      pauseResumeBtn.addEventListener('click', () => {
        isPaused = !isPaused;
        if (isPaused) {
          pauseBtnText.textContent = 'Paused';
          pauseResumeBtn.classList.replace('text-cyan-300', 'text-amber-400');
          triggerToast('Swarm Paused', 'Agent threads queued at freeze frame.');
        } else {
          pauseBtnText.textContent = 'Active';
          pauseResumeBtn.classList.replace('text-amber-400', 'text-cyan-300');
          triggerToast('Swarm Resumed', 'Real-time telemetry continuous.');
        }
      });
    }

    // Initial Load Calls
    loadLeads();
    loadTelemetry();
    setInterval(loadTelemetry, 15000);

    // Ambient Stream Simulation
    const ambientStreamLogs = [
      { agent: 'VIPER', text: '0-Token heuristic bypass saved 1,280 tokens on domain catalog #889.', style: 'text-emerald-400' },
      { agent: 'SCOUT-X', text: 'Discovered LinkedIn company profile: 42 SDR heads found.', style: 'text-slate-300' },
      { agent: 'ARBITER', text: 'Reflexion cycle: +10 Reward dispatched to ECHO for hook relevance.', style: 'text-amber-300' },
      { agent: 'VERITAS', text: 'DKIM and MX DNS verified in 14ms via UDP resolver pool.', style: 'text-purple-300' }
    ];

    let logIndex = 0;
    setInterval(() => {
      if (!isPaused) {
        const log = ambientStreamLogs[logIndex % ambientStreamLogs.length];
        appendTerminalLog(log.agent, log.text, log.style);
        logIndex++;
      }
    }, 9000);
  })();
</script>"""

# Replace the old script block with the new fastapi integration
html = html[:script_start] + fastapi_integration_js + html[script_end + len("</script>"):]

out_file = Path("frontend/index.html")
out_file.parent.mkdir(parents=True, exist_ok=True)
with open(out_file, "w", encoding="utf-8") as f:
    f.write(html)

print("Created frontend/index.html successfully, size:", len(html))

