/**
 * One Line HaDay — Home Assistant custom panel.
 *
 * Served by the One Line HaDay integration from
 * /one_line_haday_static/one-line-haday-panel.js and registered as a
 * sidebar panel via panel_custom. All API calls hit routes registered by
 * the integration's HomeAssistantView classes under /api/one_line_haday.
 *
 * Authentication is handled entirely by Home Assistant's frontend through
 * hass.callApi(). Do not use fetch() or read auth tokens manually — the
 * frontend manages token refresh and this works for local, reverse-proxy,
 * and Nabu Casa connections without any extra configuration.
 */
class OneLineHaDayPanel extends HTMLElement {
  constructor() {
    super();
    this._state = {
      journalId: null,
      entries: [],
      members: {},
      draft: '',
      visibility: 'household',
      filterUser: 'all',
      loading: false,
      error: null,
      showMembers: false,
      newMemberId: '',
      newMemberRole: 'viewer',
      retentionDays: '',
      selectedDate: null,
      viewYear: null,
      viewMonth: null, // 0–11
    };
  }

  set hass(value) {
    this._hass = value;
    this.render();
  }

  set panel(value) {
    this._panel = value;
  }

  set narrow(value) {
    this._narrow = value;
  }

  connectedCallback() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    this.render();
    if (!this._bootstrapped) {
      this._bootstrapped = true;
      this._bootstrap();
    }
  }

  get _apiBase() {
    // Path prefix for all integration API routes — no trailing slash.
    return 'one_line_haday';
  }

  get _currentUserId() {
    return (this._hass && this._hass.user && this._hass.user.id) || null;
  }

  get _currentUserName() {
    return (this._hass && this._hass.user && this._hass.user.name) || 'Unknown user';
  }

  get _isOwner() {
    return this._state.members[this._currentUserId] === 'owner';
  }

  /** Return ISO string for today (YYYY-MM-DD) in local time. */
  _getTodayIso() {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  /** Return ISO string for this day one year ago (YYYY-MM-DD) in local time. */
  _getLastYearIso() {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  /** Find the current user's entry for today, if any. */
  _getTodaysEntryForCurrentUser() {
    const today = this._getTodayIso();
    const mine = this._state.entries.filter(
      (e) => e.entry_date === today && e.author_ha_user_id === this._currentUserId
    );
    return mine[0] || null;
  }

  /** Find the current user's entry for the same day last year, if any. */
  _getLastYearEntryForCurrentUser() {
    const lastYearIso = this._getLastYearIso();
    const mine = this._state.entries.filter(
      (e) => e.entry_date === lastYearIso && e.author_ha_user_id === this._currentUserId
    );
    return mine[0] || null;
  }

  /**
   * Compute consecutive-day streak up to today for the current user.
   * A day counts if there is at least one entry with that exact date.
   */
  _computeStreakDays() {
    if (!this._currentUserId) return 0;
    const dates = new Set(
      this._state.entries
        .filter((e) => e.author_ha_user_id === this._currentUserId)
        .map((e) => e.entry_date)
    );
    let streak = 0;
    let cursor = new Date(this._getTodayIso());
    // Walk backwards one day at a time until we hit a gap.
    // Use local date math, but format as ISO YYYY-MM-DD.
    while (dates.has(
      `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, '0')}-${String(
        cursor.getDate()
      ).padStart(2, '0')}`
    )) {
      streak += 1;
      cursor.setDate(cursor.getDate() - 1);
    }
    return streak;
  }

  /**
   * Build a 7x6 month grid for the given year and month.
   * Each cell is either null (outside current month) or
   * { iso: YYYY-MM-DD, day: 1-31 }.
   */
  _buildMonthGrid(year, month) {
    const firstOfMonth = new Date(year, month, 1);
    // JS getDay(): 0=Sun..6=Sat, convert to 0=Mon..6=Sun.
    const firstWeekday = (firstOfMonth.getDay() + 6) % 7;
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const cells = [];

    for (let i = 0; i < 42; i++) {
      const dayNumber = i - firstWeekday + 1;
      if (dayNumber < 1 || dayNumber > daysInMonth) {
        cells.push(null);
      } else {
        const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(dayNumber).padStart(
          2,
          '0'
        )}`;
        cells.push({ iso, day: dayNumber });
      }
    }
    return cells;
  }

  /**
   * Route an API call through Home Assistant's authenticated frontend
   * connection. hass.callApi() manages the session, access-token refresh,
   * and works transparently for local, Nabu Casa, and reverse-proxy setups.
   */
  async _request(path, options = {}) {
    if (!this._hass?.callApi) {
      throw new Error('Home Assistant connection is not available yet.');
    }

    const method = (options.method || 'GET').toLowerCase();
    const body = options.body
      ? (typeof options.body === 'string' ? JSON.parse(options.body) : options.body)
      : undefined;

    return this._hass.callApi(method, `${this._apiBase}${path}`, body);
  }

  async _withLoading(fn) {
    this._state.loading = true;
    this.render();
    try {
      await fn();
    } catch (err) {
      this._state.error = err.message;
    } finally {
      this._state.loading = false;
      this.render();
    }
  }

  async _bootstrap() {
    // Wait until hass is fully ready with a valid callApi connection.
    if (!this._currentUserId || !this._hass?.callApi) {
      setTimeout(() => this._bootstrap(), 300);
      return;
    }
    await this._withLoading(async () => {
      const journals = await this._request('/journals');
      const journal = journals[0];
      if (!journal) throw new Error('No journal available');
      this._state.journalId = journal.id;
      this._state.retentionDays = journal.retention_days || '';

      const todayIso = this._getTodayIso();
      const today = new Date(todayIso);
      this._state.selectedDate = todayIso;
      this._state.viewYear = today.getFullYear();
      this._state.viewMonth = today.getMonth();

      await this._loadMembers();
      await this._loadEntries();
    });
  }

  async _loadEntries() {
    if (!this._state.journalId) return;
    const params = new URLSearchParams({ journal_id: this._state.journalId });
    if (this._state.filterUser !== 'all') {
      params.set('author_ha_user_id', this._state.filterUser);
    }
    this._state.entries = await this._request(`/entries?${params.toString()}`);
  }

  async _loadMembers() {
    if (!this._state.journalId) return;
    this._state.members = await this._request(`/journals/${this._state.journalId}/members`);
  }

  async _saveEntry() {
    if (!this._state.draft.trim() || !this._state.journalId) return;
    const targetDate = this._state.selectedDate || this._getTodayIso();
    await this._withLoading(async () => {
      await this._request('/entries', {
        method: 'POST',
        body: JSON.stringify({
          journal_id: this._state.journalId,
          entry_date: targetDate,
          body: this._state.draft.trim(),
          visibility: this._state.visibility,
        }),
      });
      this._state.draft = '';
      await this._loadEntries();
    });
  }

  async _uploadPhoto(entryId, file) {
    const form = new FormData();
    form.append('file', file);
    await this._withLoading(async () => {
      await this._request(`/entries/${entryId}/photos`, {
        method: 'POST',
        body: form,
      });
      await this._loadEntries();
    });
  }

  /**
   * Attach a photo while writing today's line.
   * If no entry exists yet for today, create one from the current draft
   * and visibility, then upload the photo to that new entry.
   */
  async _uploadPhotoForToday(file) {
    await this._withLoading(async () => {
      let entry = this._getTodaysEntryForCurrentUser();
      if (!entry) {
        if (!this._state.draft.trim()) {
          throw new Error('Write a line for today before attaching a photo.');
        }
        entry = await this._request('/entries', {
          method: 'POST',
          body: JSON.stringify({
            journal_id: this._state.journalId,
            entry_date: this._getTodayIso(),
            body: this._state.draft.trim(),
            visibility: this._state.visibility,
          }),
        });
        this._state.draft = '';
      }

      const form = new FormData();
      form.append('file', file);
      await this._request(`/entries/${entry.id}/photos`, {
        method: 'POST',
        body: form,
      });
      await this._loadEntries();
    });
  }

  async _deletePhoto(photoId) {
    await this._withLoading(async () => {
      await this._request(`/photos/${photoId}`, { method: 'DELETE' });
      await this._loadEntries();
    });
  }

  async _deleteEntry(entryId) {
    await this._withLoading(async () => {
      await this._request(`/entries/${entryId}`, { method: 'DELETE' });
      await this._loadEntries();
    });
  }

  async _addMember() {
    const userId = this._state.newMemberId.trim();
    if (!userId) return;
    await this._withLoading(async () => {
      await this._request(`/journals/${this._state.journalId}/members`, {
        method: 'POST',
        body: JSON.stringify({ ha_user_id: userId, role: this._state.newMemberRole }),
      });
      this._state.newMemberId = '';
      await this._loadMembers();
    });
  }

  async _removeMember(userId) {
    await this._withLoading(async () => {
      await this._request(`/journals/${this._state.journalId}/members/${userId}`, {
        method: 'DELETE',
      });
      await this._loadMembers();
    });
  }

  async _changeMemberRole(userId, role) {
    await this._withLoading(async () => {
      await this._request(`/journals/${this._state.journalId}/members`, {
        method: 'POST',
        body: JSON.stringify({ ha_user_id: userId, role }),
      });
      await this._loadMembers();
    });
  }

  async _saveRetention() {
    const raw = this._state.retentionDays;
    const retention_days = raw ? Number(raw) : null;
    if (retention_days !== null && (!Number.isInteger(retention_days) || retention_days <= 0)) {
      this._state.error = 'Retention must be a positive whole number of days, or empty to disable.';
      this.render();
      return;
    }
    await this._withLoading(async () => {
      await this._request(`/journals/${this._state.journalId}/retention`, {
        method: 'POST',
        body: JSON.stringify({ retention_days }),
      });
    });
  }

  async _exportJournal() {
    if (!this._state.journalId) return;

    await this._withLoading(async () => {
      const data = await this._request(`/journals/${this._state.journalId}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `one-line-haday-${this._state.journalId}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });
  }

  _attachHandlers() {
    const root = this.shadowRoot;

    const textarea = root.getElementById('draft-input');
    if (textarea) {
      textarea.value = this._state.draft;
      textarea.addEventListener('input', (e) => { this._state.draft = e.target.value; });
      textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) this._saveEntry();
      });
    }

    const visSelect = root.getElementById('visibility-select');
    if (visSelect) {
      visSelect.value = this._state.visibility;
      visSelect.addEventListener('change', (e) => { this._state.visibility = e.target.value; });
    }

    const filterSelect = root.getElementById('filter-select');
    if (filterSelect) {
      filterSelect.addEventListener('change', async (e) => {
        this._state.filterUser = e.target.value;
        await this._withLoading(() => this._loadEntries());
      });
    }

    const saveBtn = root.getElementById('save-btn');
    if (saveBtn) saveBtn.addEventListener('click', () => this._saveEntry());

    const todayPhotoInput = root.getElementById('today-photo-input');
    if (todayPhotoInput) {
      todayPhotoInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) this._uploadPhotoForToday(file);
      });
    }

    root.querySelectorAll('[data-photo-input]').forEach((input) => {
      input.addEventListener('change', (e) => {
        const entryId = e.target.getAttribute('data-entry-id');
        const file = e.target.files[0];
        if (file) this._uploadPhoto(entryId, file);
      });
    });

    root.querySelectorAll('[data-delete-photo]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const photoId = btn.getAttribute('data-delete-photo');
        if (confirm('Remove this photo?')) this._deletePhoto(photoId);
      });
    });

    root.querySelectorAll('[data-delete-entry]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const entryId = btn.getAttribute('data-delete-entry');
        if (confirm('Delete this entry and its photos?')) this._deleteEntry(entryId);
      });
    });

    const dismissError = root.getElementById('dismiss-error');
    if (dismissError) dismissError.addEventListener('click', () => { this._state.error = null; this.render(); });

    const settingsBtn = root.getElementById('open-settings');
    if (settingsBtn) {
      settingsBtn.addEventListener('click', () => {
        this._state.showMembers = true;
        this.render();
      });
    }

    const settingsClose = root.getElementById('close-settings');
    if (settingsClose) {
      settingsClose.addEventListener('click', () => {
        this._state.showMembers = false;
        this.render();
      });
    }

    const newMemberIdInput = root.getElementById('new-member-id');
    if (newMemberIdInput) {
      newMemberIdInput.value = this._state.newMemberId;
      newMemberIdInput.addEventListener('input', (e) => { this._state.newMemberId = e.target.value; });
    }

    const newMemberRoleSelect = root.getElementById('new-member-role');
    if (newMemberRoleSelect) {
      newMemberRoleSelect.value = this._state.newMemberRole;
      newMemberRoleSelect.addEventListener('change', (e) => { this._state.newMemberRole = e.target.value; });
    }

    const addMemberBtn = root.getElementById('add-member-btn');
    if (addMemberBtn) addMemberBtn.addEventListener('click', () => this._addMember());

    root.querySelectorAll('[data-remove-member]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const userId = btn.getAttribute('data-remove-member');
        if (confirm(`Remove ${userId} from this journal?`)) this._removeMember(userId);
      });
    });

    root.querySelectorAll('[data-member-role]').forEach((select) => {
      select.addEventListener('change', (e) => {
        const userId = select.getAttribute('data-member-role');
        this._changeMemberRole(userId, e.target.value);
      });
    });

    const retentionInput = root.getElementById('retention-input');
    if (retentionInput) {
      retentionInput.value = this._state.retentionDays;
      retentionInput.addEventListener('input', (e) => { this._state.retentionDays = e.target.value; });
    }

    const saveRetentionBtn = root.getElementById('save-retention-btn');
    if (saveRetentionBtn) saveRetentionBtn.addEventListener('click', () => this._saveRetention());

    const exportBtn = root.getElementById('export-btn');
    if (exportBtn) exportBtn.addEventListener('click', () => this._exportJournal());

    // Calendar selection: clicking a day sets selectedDate and filters the list.
    root.querySelectorAll('[data-date]').forEach((cell) => {
      const date = cell.getAttribute('data-date');
      if (!date) return;
      cell.addEventListener('click', () => {
        this._state.selectedDate = date;
        this.render();
      });
    });

    const prevBtn = root.getElementById('prev-month');
    const nextBtn = root.getElementById('next-month');
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        const year = this._state.viewYear;
        const month = this._state.viewMonth;
        const d = new Date(year, month, 1);
        d.setMonth(d.getMonth() - 1);
        this._state.viewYear = d.getFullYear();
        this._state.viewMonth = d.getMonth();
        this.render();
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        const year = this._state.viewYear;
        const month = this._state.viewMonth;
        const d = new Date(year, month, 1);
        d.setMonth(d.getMonth() + 1);
        this._state.viewYear = d.getFullYear();
        this._state.viewMonth = d.getMonth();
        this.render();
      });
    }
  }

  get _authorOptions() {
    const authors = new Map();
    this._state.entries.forEach((e) => authors.set(e.author_ha_user_id, e.author_ha_user_id));
    Object.keys(this._state.members).forEach((u) => authors.set(u, u));
    return Array.from(authors.keys());
  }

  _renderPhoto(photo, canWrite) {
    return `<div class="photo-thumb">
      <img src="${photo.url}" alt="Attached photo" loading="lazy">
      ${canWrite ? `<button class="photo-remove" data-delete-photo="${photo.id}" aria-label="Remove photo">&times;</button>` : ''}
    </div>`;
  }

  _renderEntry(entry) {
    const isMine = entry.author_ha_user_id === this._currentUserId;
    const photos = entry.photos || [];
    return `<div class="entry">
      <div class="entry-head">
        <strong>${entry.entry_date}</strong>
        <span class="pill">${entry.visibility}</span>
        <span class="small">${isMine ? 'You' : this._escape(entry.author_ha_user_id)}</span>
        ${isMine ? `<button class="ghost" data-delete-entry="${entry.id}">Delete</button>` : ''}
      </div>
      <p>${this._escape(entry.body)}</p>
      ${photos.length ? `<div class="photo-row">${photos.map((p) => this._renderPhoto(p, isMine)).join('')}</div>` : ''}
      ${isMine ? `<label class="small photo-add">Add photo<input type="file" accept="image/jpeg,image/png,image/webp,image/heic" data-photo-input data-entry-id="${entry.id}" hidden></label>` : ''}
    </div>`;
  }

  _renderMemberRow(userId, role) {
    const isSelf = userId === this._currentUserId;
    return `<div class="member-row">
      <span class="small">${isSelf ? `${this._escape(userId)} (you)` : this._escape(userId)}</span>
      ${this._isOwner && !isSelf ? `
        <select data-member-role="${userId}">
          <option value="viewer" ${role === 'viewer' ? 'selected' : ''}>Viewer</option>
          <option value="co-editor" ${role === 'co-editor' ? 'selected' : ''}>Co-editor</option>
          <option value="owner" ${role === 'owner' ? 'selected' : ''}>Owner</option>
        </select>
        <button class="ghost" data-remove-member="${userId}">Remove</button>
      ` : `<span class="pill">${role}</span>`}
    </div>`;
  }

  _renderMembersPanel() {
    const members = Object.entries(this._state.members);
    return `<div class="settings-card">
      <div class="settings-header">
        <h3>Journal settings</h3>
        <button id="close-settings" class="ghost">Close</button>
      </div>
      <h4>Members</h4>
      ${members.map(([uid, role]) => this._renderMemberRow(uid, role)).join('')}
      ${this._isOwner ? `
        <div class="row" style="margin-top:12px">
          <input id="new-member-id" placeholder="Home Assistant user ID" style="flex:1">
          <select id="new-member-role" style="width:auto">
            <option value="viewer">Viewer</option>
            <option value="co-editor">Co-editor</option>
            <option value="owner">Owner</option>
          </select>
          <button id="add-member-btn">Add</button>
        </div>
        <p class="small" style="margin-top:8px">Find a user's ID under Settings &rarr; People &rarr; select person.</p>
        <h4 style="margin-top:20px">Retention</h4>
        <div class="row">
          <input id="retention-input" type="number" min="1" placeholder="Days (empty = keep forever)" style="flex:1">
          <button id="save-retention-btn">Save</button>
        </div>
        <p class="small" style="margin-top:8px">Entries older than this are automatically purged, including their photos.</p>
        <h4 style="margin-top:20px">Export</h4>
        <button id="export-btn">Download my visible entries as JSON</button>
      ` : '<p class="small">Only the journal owner can manage members and retention.</p>'}
    </div>`;
  }

  _escape(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  render() {
    if (!this.shadowRoot) return;
    const authors = this._authorOptions;
    const todayIso = this._getTodayIso();
    const selectedDate = this._state.selectedDate || todayIso;
    const lastYearEntry = this._getLastYearEntryForCurrentUser();
    const streakDays = this._computeStreakDays();

    const viewYear = this._state.viewYear ?? new Date(todayIso).getFullYear();
    const viewMonth = this._state.viewMonth ?? new Date(todayIso).getMonth();

    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const monthLabel = `${monthNames[viewMonth]} ${viewYear}`;
    const gridCells = this._buildMonthGrid(viewYear, viewMonth);

    // Entries for the selected calendar date across years.
    const entriesForSelectedDay = this._state.entries.filter((e) => {
      if (!e.entry_date) return false;
      const parts = e.entry_date.split('-');
      const selParts = selectedDate.split('-');
      if (parts.length !== 3 || selParts.length !== 3) return false;
      const [, month, day] = parts;
      const [, selMonth, selDay] = selParts;
      if (month !== selMonth || day !== selDay) return false;
      if (this._state.filterUser !== 'all' && e.author_ha_user_id !== this._state.filterUser) return false;
      return true;
    });

    const entriesListHtml = entriesForSelectedDay.length
      ? entriesForSelectedDay
          .slice()
          .sort((a, b) => a.entry_date.localeCompare(b.entry_date))
          .map((e) => this._renderEntry(e))
          .join('')
      : '<div class="empty">No entries yet for this date. Write the first line above.</div>';

    const hasEntryForDate = (iso) => {
      return this._state.entries.some((e) => {
        if (!e.entry_date) return false;
        if (this._state.filterUser !== 'all' && e.author_ha_user_id !== this._state.filterUser) return false;
        return e.entry_date === iso;
      });
    };

    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; font-family:var(--primary-font-family,Arial); padding:16px; color:var(--primary-text-color); }
        .wrap { max-width:1200px; margin:0 auto; display:grid; gap:16px; }
        .grid { display:grid; grid-template-columns:1.4fr .9fr; gap:16px; }
        @media (max-width:800px) { .grid { grid-template-columns:1fr; } }
        .card { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:16px; padding:16px; }
        .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
        .pill { padding:6px 10px; border-radius:999px; background:var(--secondary-background-color); font-size:12px; }
        textarea,input,select,button { font:inherit; }
        textarea,input,select { width:100%; box-sizing:border-box; padding:12px; border-radius:12px; border:1px solid var(--divider-color); background:var(--input-fill-color,transparent); color:inherit; }
        textarea { min-height:110px; resize:vertical; }
        button { padding:10px 14px; border-radius:12px; border:0; background:var(--primary-color); color:var(--text-primary-color); cursor:pointer; }
        button:disabled { opacity:0.5; cursor:not-allowed; }
        button.ghost { background:transparent; color:var(--error-color,#c62828); border:1px solid var(--divider-color); width:auto; }
        .entry { padding:14px; border:1px solid var(--divider-color); border-radius:14px; background:var(--secondary-background-color); margin-top:10px; }
        .entry-head { display:flex; gap:8px; align-items:center; justify-content:space-between; flex-wrap:wrap; }
        .small { font-size:12px; color:var(--secondary-text-color); }
        .photo-add { display:inline-block; margin-top:8px; cursor:pointer; color:var(--primary-color); width:auto; }
        .photo-row { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
        .photo-thumb { position:relative; width:88px; height:88px; border-radius:10px; overflow:hidden; border:1px solid var(--divider-color); }
        .photo-thumb img { width:100%; height:100%; object-fit:cover; }
        .photo-remove { position:absolute; top:2px; right:2px; width:20px; height:20px; padding:0; border-radius:999px; line-height:1; background:rgba(0,0,0,0.6); color:#fff; }
        .error { display:flex; justify-content:space-between; align-items:center; color:#fff; background:var(--error-color,#c62828); border-radius:12px; padding:10px 14px; font-size:13px; }
        .error button { background:transparent; color:#fff; padding:2px 8px; width:auto; }
        .filter-row { display:flex; gap:8px; align-items:center; }
        .empty { padding:24px; text-align:center; color:var(--secondary-text-color); }
        .toggle-link { background:transparent; color:var(--primary-color); width:auto; padding:0; text-decoration:underline; }
        .attach-row { margin-top:12px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
        .photo-drop { position:relative; border-radius:12px; border:1px dashed var(--divider-color); padding:8px 10px; font-size:12px; color:var(--secondary-text-color); cursor:pointer; }
        .photo-drop input[type="file"] { position:absolute; inset:0; opacity:0; cursor:pointer; }
        .thumb-preview { width:48px; height:48px; border-radius:10px; border:1px solid var(--divider-color); background:var(--secondary-background-color); display:flex; align-items:center; justify-content:center; font-size:10px; color:var(--secondary-text-color); }
        .previous-year { margin-top:16px; border-top:1px solid var(--divider-color); padding-top:10px; }
        /* Calendar styles */
        .calendar-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
        .calendar-nav { display:flex; gap:8px; align-items:center; }
        .calendar-nav button { background:transparent; border:1px solid var(--divider-color); border-radius:999px; color:var(--secondary-text-color); padding:4px 10px; cursor:pointer; font-size:12px; }
        .month-label { font-weight:500; }
        .weekday-row { display:grid; grid-template-columns:repeat(7,1fr); gap:4px; margin-top:4px; }
        .weekday { text-align:center; font-size:11px; color:var(--secondary-text-color); }
        .calendar-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:4px; margin-top:8px; }
        .day-cell { border-radius:10px; border:1px solid var(--divider-color); background:var(--secondary-background-color); padding:6px 6px 10px; min-height:60px; display:flex; flex-direction:column; justify-content:space-between; cursor:pointer; }
        .day-cell.empty { opacity:0.3; cursor:default; }
        .day-cell.selected { border-color:var(--primary-color); box-shadow:0 0 0 1px var(--primary-color); }
        .day-number { font-size:12px; font-weight:500; }
        .day-number.today { border-radius:999px; border:1px solid var(--primary-color); padding:0 4px; }
        .dots-row { display:flex; gap:4px; margin-top:4px; }
        .dot { width:8px; height:8px; border-radius:999px; background:var(--divider-color); }
        .dot.has-entry { background:var(--primary-color); }
        .legend { margin-top:12px; display:flex; flex-wrap:wrap; gap:8px; font-size:11px; color:var(--secondary-text-color); }
        .legend-item { display:inline-flex; align-items:center; gap:4px; }
        .legend-dot { width:10px; height:10px; border-radius:999px; }
        /* Settings overlay */
        .settings-overlay { position:fixed; inset:0; background:rgba(0,0,0,0.5); display:flex; align-items:center; justify-content:center; z-index:1000; }
        .settings-card { max-width:480px; width:90%; background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:16px; padding:16px; }
        .settings-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
      </style>
      <div class="wrap">
        <div class="row">
          <span class="pill">Signed in as ${this._escape(this._currentUserName)}</span>
          <span class="pill">Streak: ${streakDays} day${streakDays === 1 ? '' : 's'}</span>
          <span class="pill">${this._state.loading ? 'Syncing…' : 'Up to date'}</span>
          <button id="open-settings" class="toggle-link">Settings</button>
        </div>
        ${this._state.error ? `<div class="error"><span>${this._escape(this._state.error)}</span><button id="dismiss-error" aria-label="Dismiss">&times;</button></div>` : ''}
        <div class="grid">
          <div class="card">
            <h2>Today</h2>
            <select id="visibility-select">
              <option value="household">Household — visible to all members</option>
              <option value="private">Private — only me</option>
              <option value="shared">Shared — selected people</option>
            </select>
            <label style="display:block;margin-top:12px">Entry (saving for ${selectedDate})</label>
            <textarea id="draft-input" placeholder="Write one line… (Ctrl/Cmd+Enter to save)"></textarea>
            <div class="attach-row">
              <div class="photo-drop">
                Attach photo (optional)
                <input id="today-photo-input" type="file" accept="image/jpeg,image/png,image/webp,image/heic">
              </div>
              <div class="thumb-preview">Preview</div>
            </div>
            <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
              <button id="save-btn" ${this._state.loading ? 'disabled' : ''}>Save</button>
            </div>
            ${lastYearEntry ? `
              <div class="previous-year">
                <div class="small">Last year on this day (${lastYearEntry.entry_date})</div>
                <p class="small" style="margin-top:4px;">"${this._escape(lastYearEntry.body)}"</p>
              </div>
            ` : ''}
            <div class="filter-row" style="margin-top:20px">
              <label class="small">Showing entries for calendar day ${selectedDate.slice(5)}</label>
            </div>
            <div class="filter-row" style="margin-top:8px">
              <label class="small">Filter by author</label>
              <select id="filter-select">
                <option value="all" ${this._state.filterUser === 'all' ? 'selected' : ''}>Everyone</option>
                ${authors.map((a) => `<option value="${a}" ${this._state.filterUser === a ? 'selected' : ''}>${a === this._currentUserId ? 'Me' : this._escape(a)}</option>`).join('')}
              </select>
            </div>
            ${entriesListHtml}
          </div>
          <div class="card">
            <div class="calendar-header">
              <div class="month-label">${monthLabel}</div>
              <div class="calendar-nav">
                <button id="prev-month">&lt; Prev</button>
                <button id="next-month">Next &gt;</button>
              </div>
            </div>
            <div class="weekday-row">
              <div class="weekday">Mon</div>
              <div class="weekday">Tue</div>
              <div class="weekday">Wed</div>
              <div class="weekday">Thu</div>
              <div class="weekday">Fri</div>
              <div class="weekday">Sat</div>
              <div class="weekday">Sun</div>
            </div>
            <div class="calendar-grid">
              ${gridCells.map((cell) => {
                if (!cell) {
                  return '<div class="day-cell empty"><span class="day-number"></span></div>';
                }
                const hasEntry = hasEntryForDate(cell.iso);
                const selectedClass = cell.iso === selectedDate ? ' selected' : '';
                const todayClass = cell.iso === todayIso ? ' today' : '';
                return `<div class="day-cell${selectedClass}" data-date="${cell.iso}">
                  <span class="day-number${todayClass}">${cell.day}</span>
                  <div class="dots-row">
                    <span class="dot${hasEntry ? ' has-entry' : ''}"></span>
                  </div>
                </div>`;
              }).join('')}
            </div>
            <div class="legend">
              <span class="legend-item"><span class="legend-dot" style="background: var(--primary-color);"></span> Day has a line</span>
              <span class="legend-item"><span class="legend-dot" style="background: var(--divider-color);"></span> Empty day</span>
            </div>
          </div>
        </div>
        ${this._state.showMembers ? `<div class="settings-overlay">${this._renderMembersPanel()}</div>` : ''}
      </div>
    `;
    this._attachHandlers();
  }
}

if (!customElements.get('one-line-haday-panel')) {
  customElements.define('one-line-haday-panel', OneLineHaDayPanel);
}
