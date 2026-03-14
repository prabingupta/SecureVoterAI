/* ═══════════════════════════════════════════════════════════════
   SecureVoter AI — Admin Dashboard · main.js
   Shared JS: pagination, search filtering, CSV export,
   breakdown bars, date display, keyboard shortcuts
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {

  /* ── Today's date display ──────────────────────────────────── */
  const todayEl = document.getElementById('todayStr');
  if (todayEl) {
    const opts = { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' };
    todayEl.textContent = new Date().toLocaleDateString('en-GB', opts);
  }

  /* ── Dashboard: incident table search + filter ─────────────── */
  const dashSearch       = document.getElementById('dashSearch');
  const dashStatusFilter = document.getElementById('dashStatusFilter');
  const dashTypeFilter   = document.getElementById('dashTypeFilter');
  const incidentRows     = document.querySelectorAll('#incidentBody .irow');

  function filterIncidents() {
    const q      = dashSearch?.value.toLowerCase() ?? '';
    const status = dashStatusFilter?.value ?? 'all';
    const type   = dashTypeFilter?.value   ?? 'all';
    incidentRows.forEach(row => {
      const text     = row.textContent.toLowerCase();
      const rowType  = row.dataset.type   ?? '';
      const rowStat  = row.dataset.status ?? '';
      const matchQ   = !q      || text.includes(q);
      const matchSt  = status === 'all' || rowStat === status;
      const matchTy  = type   === 'all' || rowType === type;
      row.style.display = (matchQ && matchSt && matchTy) ? '' : 'none';
    });
    updatePgInfo();
  }
  dashSearch?.addEventListener('input',  filterIncidents);
  dashStatusFilter?.addEventListener('change', filterIncidents);
  dashTypeFilter?.addEventListener('change',   filterIncidents);

  function updatePgInfo() {
    const pgInfo = document.getElementById('pgInfo');
    if (!pgInfo) return;
    const visible = [...incidentRows].filter(r => r.style.display !== 'none').length;
    pgInfo.textContent = visible === incidentRows.length
      ? `Showing all ${incidentRows.length} records`
      : `Showing ${visible} of ${incidentRows.length} records`;
  }
  updatePgInfo();


  /* ── Fraud Log Report: search + filter + CSV export ────────── */
  const rptSearch      = document.getElementById('rptSearch');
  const rptTypeFilter  = document.getElementById('rptTypeFilter');
  const rptStatusFilter= document.getElementById('rptStatusFilter');
  const rptRows        = document.querySelectorAll('#rptBody .rpt-row');
  const rptRowCount    = document.getElementById('rptRowCount');

  function filterReport() {
    const q      = rptSearch?.value.toLowerCase() ?? '';
    const type   = rptTypeFilter?.value   ?? 'all';
    const status = rptStatusFilter?.value ?? 'all';
    let visible = 0;
    rptRows.forEach(row => {
      const text    = row.textContent.toLowerCase();
      const rowType = row.dataset.type   ?? '';
      const rowStat = row.dataset.status ?? '';
      const show = (!q || text.includes(q))
                && (type   === 'all' || rowType === type)
                && (status === 'all' || rowStat === status);
      row.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    if (rptRowCount) rptRowCount.textContent = `${visible} record${visible !== 1 ? 's' : ''}`;
  }
  rptSearch?.addEventListener('input',  filterReport);
  rptTypeFilter?.addEventListener('change',   filterReport);
  rptStatusFilter?.addEventListener('change', filterReport);
  filterReport(); // init

  /* CSV Export */
  document.getElementById('rptExportCsv')?.addEventListener('click', exportCSV);
  function exportCSV() {
    const table = document.getElementById('rptTable');
    if (!table) return;
    const rows = [...table.querySelectorAll('thead tr, tbody tr')]
      .filter(r => r.closest('tbody') ? r.style.display !== 'none' : true);
    const csv = rows.map(row =>
      [...row.querySelectorAll('th, td')]
        .map(cell => `"${cell.innerText.replace(/\n/g, ' ').replace(/"/g, '""')}"`)
        .join(',')
    ).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `fraud-log-${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }


  /* ── Notifications: tab filter + search ────────────────────── */
  const notifCards = document.querySelectorAll('.notif-card');
  document.querySelectorAll('.ntab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.ntab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const f = tab.dataset.filter;
      notifCards.forEach(card => {
        const type     = card.dataset.type     ?? '';
        const reviewed = card.dataset.reviewed ?? 'false';
        let show = true;
        if (f === 'unread')  show = reviewed === 'false';
        else if (f !== 'all') show = type === f;
        card.style.display = show ? '' : 'none';
      });
    });
  });

  document.getElementById('notifSearch')?.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    notifCards.forEach(card => {
      card.style.display = card.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });


  /* ── Breakdown bars (fraud log report) ─────────────────────── */
  const grid = document.getElementById('breakdownGrid');
  if (grid && rptRows.length > 0) {
    const counts = { spoof_attempt:0, face_mismatch:0, too_many_attempts:0, multiple_faces:0, unknown_device:0 };
    rptRows.forEach(r => { if (counts[r.dataset.type] !== undefined) counts[r.dataset.type]++; });
    const total = Object.values(counts).reduce((a,b)=>a+b,0) || 1;
    const labels = {
      spoof_attempt: 'Spoof Attempt', face_mismatch: 'Face Mismatch',
      too_many_attempts: 'Too Many Attempts', multiple_faces: 'Multiple Faces',
      unknown_device: 'Unknown Device'
    };
    const colors = {
      spoof_attempt: '#991B1B', face_mismatch: '#92400E',
      too_many_attempts: '#1E40AF', multiple_faces: '#7C3AED', unknown_device: '#0D9488'
    };
    Object.entries(counts).forEach(([type, count]) => {
      if (count === 0) return;
      const pct = Math.round((count / total) * 100);
      const div = document.createElement('div');
      div.className = 'bbc';
      div.innerHTML = `
        <div class="bbc-row">
          <span class="bbc-name">${labels[type]}</span>
          <span class="bbc-val" style="color:${colors[type]};">${count}</span>
        </div>
        <div class="bbc-track">
          <div class="bbc-fill" style="width:0%;background:${colors[type]};" data-target="${pct}"></div>
        </div>`;
      grid.appendChild(div);
    });
    // Animate bars
    requestAnimationFrame(() => {
      document.querySelectorAll('.bbc-fill').forEach(bar => {
        bar.style.width = bar.dataset.target + '%';
      });
    });
  }


  /* ── Keyboard shortcut: ⌘K / Ctrl+K focus search ────────────── */
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      document.getElementById('globalSearch')?.focus();
    }
  });


  /* ── Election table: search + filter pills ─────────────────── */
  const electionSearch = document.getElementById('electionSearch');
  const electionRows   = document.querySelectorAll('#electionsTable tbody tr');
  electionSearch?.addEventListener('input', () => {
    const q = electionSearch.value.toLowerCase();
    electionRows.forEach(r => { r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none'; });
  });
  document.querySelectorAll('.filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      const f = pill.dataset.filter;
      electionRows.forEach(r => {
        r.style.display = (f === 'all' || r.dataset.status === f) ? '' : 'none';
      });
    });
  });


  /* ── Voters: search + filter pills + stat counters ─────────── */
  const voterRows = document.querySelectorAll('#votersTable tbody tr');
  document.getElementById('voterSearch')?.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    voterRows.forEach(r => { r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none'; });
  });
  document.querySelectorAll('.filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      const f = pill.dataset.filter;
      voterRows.forEach(r => { r.style.display = (f === 'all' || r.dataset.status === f) ? '' : 'none'; });
    });
  });
  // Stat counters
  let approved = 0, pending = 0;
  voterRows.forEach(r => {
    if (r.dataset.status === 'approved') approved++;
    else if (r.dataset.status === 'pending') pending++;
  });
  const approvedEl = document.getElementById('approvedCount');
  const pendingEl  = document.getElementById('pendingCount');
  if (approvedEl) approvedEl.textContent = approved;
  if (pendingEl)  pendingEl.textContent  = pending;


  /* ── Candidate search + election filter ─────────────────────── */
  const candCards = document.querySelectorAll('.candidate-admin-card');
  document.getElementById('candidateSearch')?.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    candCards.forEach(c => { c.style.display = c.dataset.name?.includes(q) ? '' : 'none'; });
  });
  document.getElementById('electionFilter')?.addEventListener('change', (e) => {
    const val = e.target.value;
    candCards.forEach(c => { c.style.display = (val === 'all' || c.dataset.election === val) ? '' : 'none'; });
  });


  /* ── Delete Election Modal ────────────────────────────────────── */
  const deleteElecModal = document.getElementById('deleteElectionModal');
  const deleteElecTitle = document.getElementById('deleteElectionTitle');
  const confirmDelElec  = document.getElementById('confirmDeleteElec');
  document.querySelectorAll('[data-modal="deleteElectionModal"]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (deleteElecTitle) deleteElecTitle.textContent = btn.dataset.electionTitle;
      if (confirmDelElec)  confirmDelElec.href = `/admin-dashboard/elections/${btn.dataset.electionId}/delete/`;
      deleteElecModal?.classList.add('active');
    });
  });
  document.getElementById('closeDeleteModal')?.addEventListener('click',  () => deleteElecModal?.classList.remove('active'));
  document.getElementById('cancelDeleteElec')?.addEventListener('click',  () => deleteElecModal?.classList.remove('active'));
  deleteElecModal?.addEventListener('click', e => { if (e.target === deleteElecModal) deleteElecModal.classList.remove('active'); });


  /* ── Delete Candidate Modal ─────────────────────────────────── */
  const delCandModal = document.getElementById('deleteCandidateModal');
  const delCandName  = document.getElementById('deleteCandidateName');
  const confirmDelCand = document.getElementById('confirmDeleteCand');
  document.querySelectorAll('[data-modal="deleteCandidateModal"]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (delCandName)    delCandName.textContent = btn.dataset.candidateName;
      if (confirmDelCand) confirmDelCand.href = `/admin-dashboard/candidates/${btn.dataset.candidateId}/delete/`;
      delCandModal?.classList.add('active');
    });
  });
  document.getElementById('closeDeleteCandModal')?.addEventListener('click', () => delCandModal?.classList.remove('active'));
  document.getElementById('cancelDeleteCand')?.addEventListener('click',     () => delCandModal?.classList.remove('active'));
  delCandModal?.addEventListener('click', e => { if (e.target === delCandModal) delCandModal.classList.remove('active'); });


  /* ── Reject Voter Modal ──────────────────────────────────────── */
  const rejectModal  = document.getElementById('rejectModal');
  const rejectForm   = document.getElementById('rejectForm');
  const rejectNameEl = document.getElementById('rejectVoterName');
  document.querySelectorAll('[data-modal="rejectModal"]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (rejectNameEl) rejectNameEl.textContent = btn.dataset.voterName;
      if (rejectForm)   rejectForm.action = `/admin-dashboard/voters/${btn.dataset.voterId}/reject/`;
      rejectModal?.classList.add('active');
    });
  });
  document.getElementById('closeRejectModal')?.addEventListener('click', () => rejectModal?.classList.remove('active'));
  document.getElementById('cancelReject')?.addEventListener('click',     () => rejectModal?.classList.remove('active'));
  rejectModal?.addEventListener('click', e => { if (e.target === rejectModal) rejectModal.classList.remove('active'); });


  /* ── Escape closes any open modal ──────────────────────────── */
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
  });


  /* ── Candidate photo preview ────────────────────────────────── */
  document.getElementById('id_photo')?.addEventListener('change', function () {
    const file = this.files[0];
    if (!file) return;
    const wrap = document.getElementById('photoPreviewWrap');
    const img  = document.getElementById('photoPreview');
    const reader = new FileReader();
    reader.onload = (e) => {
      if (img)  img.src = e.target.result;
      if (wrap) wrap.style.display = 'block';
    };
    reader.readAsDataURL(file);
  });

});