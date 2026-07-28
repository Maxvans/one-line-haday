/**
 * One Line HaDay — Home Assistant custom panel.
 *
 * Renders a per-user "one line a day" journal view backed by the
 * One Line HaDay add-on API (reached via Home Assistant ingress).
 * Supports multiple household users writing to the same day,
 * filtering entries by author, and uploading photos to an entry.
 */
class OneLineHaDayPanel extends HTMLElement {
  constructor() {
    super();
    this._state = {
      journalId: null,
      entries: [],
      draft: '',
      visibility: 'household',
      filterUser: 'all',
      loading: false,
      error: null,
    };
  }

  set hass(value) {
    this._hass = value;
    this.render();
  }

  set panel(value) {
    this._panel = value;
    this.render();
  }

  set narrow(value) {
    this._narrow = value;
    this.render();
  }

  connectedCallback() {
    this.attachShadow({ mode: 'open' });
    this.render();
    this._bootstrap();
  }

  get _apiBase() {
    // Ingress-mounted add-on API base path.
    return (this._panel && this._panel.config && this._panel.config.ingress_url) || '/api/one_line_haday';
  }

  get _currentUserId() {
    return (this._hass && this._hass.user && this._hass.user.id) || null;
  }

  get _currentUserName() {
    return (this._hass && this._hass.user && this._hass.user.name) || 'Unknown user';
  }

  async _request(path, options = {}) {
    const res = await fetch(`${this._apiBase}${path}`, {
      ...options,
      headers: {
        'X-Remote-User-Id': this._currentUserId || '',
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(options.headers || {}),
      },
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `Request failed: ${res.status}`);
    }
    return res.status === 204 ? null : res.json();
  }

  async _bootstrap() {
    if (!this._currentUserId) return;
    this._state.loading = true;
    this.render();
    try {
      const journals = await this._request('/journals');
      let journal = journals[0];
      if (!journal) {
        journal = await this._request('/journals', {
          method: 'POST',
          body: JSON.stringify({ title: 'Household Journal', visibility: 'household' }),
        });
        journal = { id: journal.id };
      }
      this._state.journalId = journal.id;
      await this._loadEntries();
    } catch (err) {
      this._state.error = err.message;
    } finally {
      this._state.loading = false;
      this.render();
    }
  }

  async _loadEntries() {
    if (!this._state.journalId) return;
    const params = new URLSearchParams({ journal_id: this._state.journalId });
    if (this._state.filterUser !== 'all') {
      params.set('author_ha_user_id', this._state.filterUser);
    }
    this._state.entries = await this._request(`/entries?${params.toString()}`);
  }

  async _saveEntry() {
    if (!this._state.draft.trim() || !this._state.journalId) return;
    this._state.loading = true;
    this.render();
    try {
      await this._request('/entries', {
        method: 'POST',
        body: JSON.stringify({
          journal_id: this._state.journalId,
          entry_date: new Date().toISOString().slice(0, 10),
          body: this._state.draft.trim(),
          visibility: this._state.visibility,
        }),
      });
      this._state.draft = '';
      await this._loadEntries();
    } catch (err) {
      this._state.error = err.message;
    } finally {
      this._state.loading = false;
      this.render();
    }
  }

  async _uploadPhoto(entryId, file) {
    const form = new FormData();
    form.append('file', file);
    this._state.loading = true;
    this.render();
    try {
      await this._request(`/entries/${entryId}/photos`, { method: 'POST', body: form });
      await this._loadEntries();
    } catch (err) {
      this._state.error = err.message;
    } finally {
      this._state.loading = false;
      this.render();
    }
  }

  async _deleteEntry(entryId) {
    this._state.loading = true;
    this.render();
    try {
      await this._request(`/entries/${entryId}`, { method: 'DELETE' });
      await this._loadEntries();
    } catch (err) {
      this._state.error = err.message;
    } finally {
      this._state.loading = false;
      this.render();
    }
  }

  _attachHandlers() {
    const root = this.shadowRoot;
    const textarea = root.getElementById('draft-input');
    if (textarea) {
      textarea.value = this._state.draft;
      textarea.addEventListener('input', (e) => { this._state.draft = e.target.value; });
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
        await this._loadEntries();
        this.render();
      });
    }

    const saveBtn = root.getElementById('save-btn');
    if (saveBtn) saveBtn.addEventListener('click', () => this._saveEntry());

    root.querySelectorAll('[data-photo-input]').forEach((input) => {
      input.addEventListener('change', (e) => {
        const entryId = e.target.getAttribute('data-entry-id');
        const file = e.target.files[0];
        if (file) this._uploadPhoto(entryId, file);
      });
    });

    root.querySelectorAll('[data-delete-entry]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const entryId = btn.getAttribute('data-delete-entry');
        if (confirm('Delete this entry and its photos?')) this._deleteEntry(entryId);
      });
    });
  }

  _authorOptions() {
    const authors = new Map();
    this._state.entries.forEach((e) => authors.set(e.author_ha_user_id, e.author_ha_user_id));
    return Array.from(authors.keys());
  }

  _renderEntry(entry) {
    const isMine = entry.author_ha_user_id === this._currentUserId;
    return `
      <div class="entry">
        <div class="entry-head">
          <strong>${entry.entry_date}</strong>
          <span class="pill">${entry.visibility}</span>
          ${isMine ? `<button class="ghost" data-delete-entry="${entry.id}">Delete</button>` : ''}
        </div>
        <p>${this._escape(entry.body)}</p>
        <label class="small photo-add">
          Add photo
          <input type="file" accept="image/*" data-photo-input data-entry-id="${entry.id}" hidden />
        </label>
      </div>`;
  }

  _escape(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  render() {
    if (!this.shadowRoot) return;
    const authors = this._authorOptions();
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;font-family:var(--primary-font-family,Arial);padding:16px;color:var(--primary-text-color)}
        .wrap{max-width:1200px;margin:0 auto;display:grid;gap:16px}
        .grid{display:grid;grid-template-columns:1.4fr .9fr;gap:16px}
        .card{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:16px;padding:16px}
        .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
        .pill{padding:6px 10px;border-radius:999px;background:var(--secondary-background-color);font-size:12px}
        textarea,input,select,button{font:inherit}
        textarea,input,select{width:100%;box-sizing:border-box;padding:12px;border-radius:12px;border:1px solid var(--divider-color);background:var(--input-fill-color,transparent);color:inherit}
        textarea{min-height:110px}
        button{padding:10px 14px;border-radius:12px;border:0;background:var(--primary-color);color:var(--text-primary-color);cursor:pointer}
        button.ghost{background:transparent;color:var(--error-color,#c62828);border:1px solid var(--divider-color)}
        .entry{padding:14px;border:1px solid var(--divider-color);border-radius:14px;background:var(--secondary-background-color);margin-top:10px}
        .entry-head{display:flex;gap:8px;align-items:center;justify-content:space-between}
        .small{font-size:12px;color:var(--secondary-text-color)}
        .photo-add{display:inline-block;margin-top:8px;cursor:pointer;color:var(--primary-color);width:auto}
        .error{color:var(--error-color,#c62828);font-size:13px}
        .filter-row{display:flex;gap:8px;align-items:center}
      </style>
      <div class="wrap">
        <div class="row">
          <span class="pill">Signed in as ${this._escape(this._currentUserName)}</span>
          <span class="pill">${this._state.loading ? 'Syncing…' : 'Up to date'}</span>
        </div>
        ${this._state.error ? `<div class="error">${this._escape(this._state.error)}</div>` : ''}
        <div class="grid">
          <div class="card">
            <h2>Today</h2>
            <select id="visibility-select">
              <option value="household">Household (visible to all members)</option>
              <option value="private">Private (only me)</option>
              <option value="shared">Shared (selected people)</option>
            </select>
            <label style="display:block;margin-top:12px">Entry</label>
            <textarea id="draft-input" placeholder="Write one line..."></textarea>
            <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
              <button id="save-btn" ${this._state.loading ? 'disabled' : ''}>Save</button>
            </div>

            <div class="filter-row" style="margin-top:20px">
              <label class="small">Filter by author</label>
              <select id="filter-select">
                <option value="all" ${this._state.filterUser === 'all' ? 'selected' : ''}>Everyone</option>
                ${authors.map((a) => `<option value="${a}" ${this._state.filterUser === a ? 'selected' : ''}>${a === this._currentUserId ? 'Me' : a}</option>`).join('')}
              </select>
            </div>

            ${this._state.entries.length
              ? this._state.entries.map((e) => this._renderEntry(e)).join('')
              : '<p class="small" style="margin-top:12px">No entries yet. Write the first line for today.</p>'}
          </div>
          <div class="card">
            <h3>Permissions</h3>
            <div class="small">Household entries are visible to every journal member. Private entries are visible only to their author. Shared entries are visible only to the people explicitly granted access.</div>
          </div>
        </div>
      </div>`;
    this._attachHandlers();
  }
}

customElements.define('one-line-haday-panel', OneLineHaDayPanel);
